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

# --- 1. FIXED DATABASE CONNECTION ---
@st.cache_resource
def get_db_collection():
    """
    Connects to Astra DB. 
    Fixes 'unexpected keyword' error by checking list_collection_names first.
    """
    try:
        token = st.secrets["ASTRA_DB_APPLICATION_TOKEN"]
        endpoint = st.secrets["ASTRA_DB_API_ENDPOINT"]
        
        client = DataAPIClient(token)
        db = client.get_database_by_api_endpoint(endpoint)
        
        # Check if collection exists before creating
        existing_collections = db.list_collection_names()
        
        if "resume_transactions" in existing_collections:
            return db.get_collection("resume_transactions")
        else:
            return db.create_collection("resume_transactions")
            
    except Exception as e:
        st.error(f"⚠️ DB Connection failed: {e}")
        return None

def log_transaction(data):
    """Saves data to Astra DB."""
    collection = get_db_collection()
    if collection:
        data["timestamp"] = datetime.datetime.now().isoformat()
        try:
            collection.insert_one(data)
        except Exception as e:
            st.error(f"Failed to save log: {e}")

def fetch_all_transactions():
    """Retrieves logs for Admin Dashboard."""
    collection = get_db_collection()
    if not collection:
        return []
    # Fetch latest 50 records
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
    Return JSON: {{ "match_score": 0-100 }}
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
        return {"match_score": 0}

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

# --- PAGE: GENERATOR ---

def app_interface():
    st.header("📄 Generator Mode")
    
    # Initialize Session State variables if they don't exist
    if "generated_data" not in st.session_state:
        st.session_state.generated_data = None

    # Inputs
    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader("Upload Resume", type=["pdf", "docx"])
    with col2:
        jd_text = st.text_area("Job Description", height=150)
    
    # Generate Button
    if st.button("Generate Resume and Cover Letter", type="primary"):
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
            
            # 4. SAVE TO SESSION STATE (This fixes the reset issue)
            st.session_state.generated_data = {
                "original_score": original_stats.get('match_score', 0),
                "new_score": new_stats.get('match_score', 0),
                "new_resume": new_resume,
                "cover_letter": cover_letter
            }
            
            st.success("Done!")

    # --- RESULTS DISPLAY (Outside the button block) ---
    # This ensures results stay visible even when you click "Download"
    
    if st.session_state.generated_data:
        data = st.session_state.generated_data
        
        st.divider()
        
        # Stats
        c1, c2 = st.columns(2)
        with c1:
            st.metric("Original Score", f"{data['original_score']}%")
        with c2:
            st.metric("New Score", f"{data['new_score']}%", delta=data['new_score'] - data['original_score'])

        # Download Buttons
        d1, d2 = st.columns(2)
        
        with d1:
            st.subheader("Optimized Resume")
            st.text_area("Preview Resume", data['new_resume'], height=300)
            st.download_button(
                label="⬇️ Download Resume (.docx)",
                data=create_docx(data['new_resume']),
                file_name="Optimized_Resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            
        with d2:
            st.subheader("Cover Letter")
            st.text_area("Preview Cover Letter", data['cover_letter'], height=300)
            st.download_button(
                label="⬇️ Download Cover Letter (.docx)",
                data=create_docx(data['cover_letter']),
                file_name="Cover_Letter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

# --- PAGE: ADMIN DASHBOARD ---

def admin_dashboard():
    st.header("🔒 Admin Transaction Logs")
    
    pwd = st.text_input("Enter Admin Password", type="password")
    if pwd != st.secrets.get("ADMIN_PASSWORD", "admin"):
        st.info("Please enter password.")
        st.stop()

    if st.button("Refresh Logs"):
        st.rerun()

    transactions = fetch_all_transactions()
    
    if not transactions:
        st.info("No transactions found.")
        return

    # Summary Table
    df = pd.DataFrame(transactions)
    if not df.empty:
        st.dataframe(
            df[['timestamp', 'original_score', 'new_score', 'file_name']],
            use_container_width=True,
            hide_index=True
        )

    st.divider()
    
    # Details & Downloads
    options = {f"{t.get('timestamp', 'N/A')} - {t.get('file_name', 'Unknown')}": t for t in transactions}
    selected_option = st.selectbox("Select Transaction to View:", list(options.keys()))

    if selected_option:
        record = options[selected_option]
        
        # Stats
        m1, m2, m3 = st.columns(3)
        m1.text(f"Date: {record.get('timestamp')}")
        m2.metric("Original", f"{record.get('original_score')}%")
        m3.metric("New", f"{record.get('new_score')}%")

        # Downloads
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            st.download_button("📄 Orig. Resume", create_docx(record.get('original_resume_text', '')), f"Orig_{record.get('file_name')}.docx")
        with d2:
            st.download_button("🎯 JD", record.get('job_description', '').encode(), "JD.txt")
        with d3:
            st.download_button("🚀 New Resume", create_docx(record.get('generated_resume', '')), "New_Resume.docx")
        with d4:
            st.download_button("✉️ Cover Letter", create_docx(record.get('generated_cover_letter', '')), "Cover_Letter.docx")

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
