import streamlit as st
import openai
import pdfplumber
import docx
from io import BytesIO
import json
import datetime
import pandas as pd
from astrapy import DataAPIClient

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Resume Architect", layout="wide", page_icon="🚀")

# --- DATABASE CONNECTION ---
@st.cache_resource
def get_db_collection():
    try:
        token = st.secrets["ASTRA_DB_APPLICATION_TOKEN"]
        endpoint = st.secrets["ASTRA_DB_API_ENDPOINT"]
        client = DataAPIClient(token)
        db = client.get_database_by_api_endpoint(endpoint)
        return db.create_collection("resume_transactions", check_exists=False)
    except Exception as e:
        st.error(f"⚠️ DB Connection failed: {e}")
        return None

def log_transaction(data):
    """Saves all text data to Astra DB for future retrieval."""
    collection = get_db_collection()
    if collection:
        # Add timestamp if not present
        data["timestamp"] = datetime.datetime.now().isoformat()
        try:
            collection.insert_one(data)
        except Exception as e:
            print(f"Failed to log: {e}")

def fetch_all_transactions():
    """Retrieves all logs from Astra DB."""
    collection = get_db_collection()
    if not collection:
        return []
    
    # Fetch all documents (limit to 50 for performance, sort by newest)
    cursor = collection.find({}, sort={"timestamp": -1}, limit=50)
    return list(cursor)

# --- HELPER FUNCTIONS ---

def create_docx(text):
    doc = docx.Document()
    for line in text.split('\n'):
        doc.add_paragraph(line)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

# --- AI LOGIC ---

def analyze_resume(client, resume_text, jd_text):
    prompt = f"""
    Act as a strict ATS. Compare Resume vs JD.
    Return JSON: {{ "match_score": 0-100, "tips": ["tip1", "tip2"] }}
    RESUME: {resume_text[:3000]}
    JD: {jd_text[:1500]}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Output valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={ "type": "json_object" },
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)
    except:
        return {"match_score": 0, "tips": []}

def optimize_resume(client, resume_text, jd_text):
    prompt = f"Rewrite this resume to beat ATS (Keyword Mirroring). \nRESUME: {resume_text}\nJD: {jd_text}"
    response = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.5
    )
    return response.choices[0].message.content

def generate_cover_letter(client, resume_text, jd_text):
    prompt = f"Write a professional cover letter. \nRESUME: {resume_text}\nJD: {jd_text}"
    response = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# --- PAGES ---

def app_interface():
    st.header("📄 Generator Mode")
    
    # Inputs
    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader("Upload Resume", type=["pdf", "docx"])
    with col2:
        jd_text = st.text_area("Job Description", height=150)
    
    if st.button("Generate & Log", type="primary"):
        if not uploaded_file or not jd_text:
            st.warning("Please provide both resume and JD.")
            return

        client = openai.OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        
        with st.status("Processing...", expanded=True):
            # 1. Extract
            st.write("Reading file...")
            if uploaded_file.name.endswith(".pdf"):
                resume_text = extract_text_from_pdf(uploaded_file)
            else:
                resume_text = extract_text_from_docx(uploaded_file)

            # 2. Analyze & Generate
            st.write("Analyzing & Optimizing...")
            original_stats = analyze_resume(client, resume_text, jd_text)
            new_resume = optimize_resume(client, resume_text, jd_text)
            cover_letter = generate_cover_letter(client, resume_text, jd_text)
            new_stats = analyze_resume(client, new_resume, jd_text)
            
            # 3. Log to DB
            st.write("Saving to Database...")
            log_transaction({
                "original_resume_text": resume_text,
                "job_description": jd_text,
                "generated_resume": new_resume,
                "generated_cover_letter": cover_letter,
                "original_score": original_stats.get('match_score', 0),
                "new_score": new_stats.get('match_score', 0),
                "file_name": uploaded_file.name
            })
            
            st.success("Done!")

        # Display & Download
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Original Score", f"{original_stats.get('match_score',0)}%")
            st.download_button("⬇️ Download New Resume", create_docx(new_resume), "Optimized_Resume.docx")
        with c2:
            st.metric("New Score", f"{new_stats.get('match_score',0)}%")
            st.download_button("⬇️ Download Cover Letter", create_docx(cover_letter), "Cover_Letter.docx")

def admin_dashboard():
    st.header("🔒 Admin Transaction Logs")
    
    # Password Protection
    pwd = st.text_input("Enter Admin Password", type="password")
    if pwd != st.secrets.get("ADMIN_PASSWORD", "admin"):
        st.stop()

    st.success("Authenticated")
    
    if st.button("Refresh Logs"):
        st.rerun()

    # Fetch Data
    transactions = fetch_all_transactions()
    
    if not transactions:
        st.info("No transactions found in database.")
        return

    # 1. Summary Table
    df = pd.DataFrame(transactions)
    if '_id' in df.columns: 
        df['_id'] = df['_id'].astype(str) # Convert Object ID to string
        
    # Display clean table
    st.dataframe(
        df[['timestamp', 'original_score', 'new_score', 'file_name']],
        use_container_width=True,
        hide_index=True
    )

    st.divider()
    st.subheader("Detailed View & Downloads")

    # 2. Detail Selector
    # Create a dropdown to select a specific transaction by Timestamp + File Name
    options = {f"{t.get('timestamp', 'N/A')} - {t.get('file_name', 'Unknown')}": t for t in transactions}
    selected_option = st.selectbox("Select a Transaction to view details:", options.keys())

    if selected_option:
        record = options[selected_option]
        
        # Stats Row
        m1, m2, m3 = st.columns(3)
        m1.info(f"📅 **Date:** {record.get('timestamp')}")
        m2.metric("Original Match", f"{record.get('original_score')}%")
        m3.metric("New Match", f"{record.get('new_score')}%", delta=record.get('new_score')-record.get('original_score'))

        # Download Row
        st.markdown("### 📥 Download Assets")
        d1, d2, d3, d4 = st.columns(4)
        
        with d1:
            # Re-create Original Resume as DOCX
            orig_docx = create_docx(record.get('original_resume_text', 'Error'))
            st.download_button("📄 Original Resume", orig_docx, f"Original_{record.get('file_name', 'resume')}.docx")
            
        with d2:
            # Job Description as Text File
            jd_bytes = record.get('job_description', '').encode('utf-8')
            st.download_button("🎯 Job Description", jd_bytes, "Job_Description.txt")
            
        with d3:
            # Generated Resume
            new_docx = create_docx(record.get('generated_resume', 'Error'))
            st.download_button("🚀 Optimized Resume", new_docx, "Optimized_Resume.docx")
            
        with d4:
            # Cover Letter
            cl_docx = create_docx(record.get('generated_cover_letter', 'Error'))
            st.download_button("✉️ Cover Letter", cl_docx, "Cover_Letter.docx")

        # Preview Expander
        with st.expander("See Text Preview"):
            c1, c2 = st.columns(2)
            c1.text_area("Original Text", record.get('original_resume_text', '')[:1000] + "...", height=200)
            c2.text_area("Optimized Text", record.get('generated_resume', '')[:1000] + "...", height=200)

# --- MAIN ROUTER ---

def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to:", ["Generator", "Admin Dashboard"])

    if page == "Generator":
        app_interface()
    else:
        admin_dashboard()

if __name__ == "__main__":
    main()
