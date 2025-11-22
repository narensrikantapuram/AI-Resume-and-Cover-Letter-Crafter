import streamlit as st
import openai
import pdfplumber
import docx
from io import BytesIO
import json
import datetime
from astrapy import DataAPIClient # Import Astra Client

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Resume Architect", layout="wide")

# --- DATABASE CONNECTION ---
def get_db_collection():
    """Connects to Astra DB and returns the collection object."""
    try:
        # 1. Load secrets
        token = st.secrets["ASTRA_DB_APPLICATION_TOKEN"]
        endpoint = st.secrets["ASTRA_DB_API_ENDPOINT"]
        
        # 2. Initialize Client
        client = DataAPIClient(token)
        db = client.get_database_by_api_endpoint(endpoint)
        
        # 3. Create/Get Collection (Table)
        # We will name our collection 'resume_transactions'
        return db.create_collection("resume_transactions", check_exists=False)
    except Exception as e:
        st.error(f"⚠️ Database Connection Error: {e}")
        return None

def log_transaction_to_astra(original_text, jd_text, optimized_text, scores):
    """Saves the interaction details to Astra DB."""
    collection = get_db_collection()
    if not collection:
        return

    # Create the document (JSON object)
    transaction_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "job_description_snippet": jd_text[:200] + "...", # Save space, just store start
        "original_match_score": scores['original'],
        "new_match_score": scores['new'],
        "improvement_percentage": scores['new'] - scores['original'],
        "original_resume_length": len(original_text),
        "optimized_resume_length": len(optimized_text),
        "status": "success"
    }

    # Insert into DB
    try:
        collection.insert_one(transaction_data)
        print("✅ Transaction logged to Astra DB")
    except Exception as e:
        print(f"❌ Failed to log transaction: {e}")

# --- HELPER FUNCTIONS ---

def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

def create_docx(text):
    doc = docx.Document()
    for line in text.split('\n'):
        doc.add_paragraph(line)
    buffer = BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# --- AI LOGIC (UNCHANGED) ---

def analyze_resume(client, resume_text, jd_text, model="gpt-4o"):
    prompt = f"""
    Act as a strict ATS. Compare Resume vs JD.
    Return JSON: {{ "match_score": 0-100, "tips": ["tip1", "tip2"] }}
    RESUME: {resume_text[:3000]}
    JD: {jd_text[:1500]}
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        response_format={ "type": "json_object" },
        temperature=0.2
    )
    return json.loads(response.choices[0].message.content)

def optimize_resume(client, resume_text, jd_text, model="gpt-4o"):
    prompt = f"""
    Rewrite resume to beat ATS. Use Keyword Mirroring.
    RESUME: {resume_text}
    JD: {jd_text}
    """
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content

def generate_cover_letter(client, resume_text, jd_text, model="gpt-4o"):
    prompt = f"Write a cover letter. RESUME: {resume_text} JD: {jd_text}"
    response = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# --- MAIN UI ---

def main():
    st.title("🚀 AI Resume Architect")
    
    # Sidebar
    with st.sidebar:
        st.header("Configuration")
        model_choice = st.selectbox("Model", ["gpt-4o", "gpt-4-turbo"])
        
        # Helper to verify DB connection (Optional)
        if st.button("Test DB Connection"):
            coll = get_db_collection()
            if coll: st.success("Connected to Astra DB!")

    # Load Secrets
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except:
        st.error("Secrets not found. Please set up secrets.toml")
        st.stop()

    # UI Inputs
    col1, col2 = st.columns(2)
    with col1:
        uploaded_file = st.file_uploader("Upload Resume (PDF/DOCX)", type=["pdf", "docx"])
    with col2:
        jd_text = st.text_area("Paste Job Description", height=200)

    if st.button("Generate Application", type="primary"):
        if not uploaded_file or not jd_text:
            st.error("Missing inputs")
            return

        client = openai.OpenAI(api_key=api_key)
        
        with st.status("Processing...", expanded=True) as status:
            
            # 1. Extract
            status.write("Reading file...")
            if uploaded_file.name.endswith(".pdf"):
                resume_text = extract_text_from_pdf(uploaded_file)
            else:
                resume_text = extract_text_from_docx(uploaded_file)

            # 2. Analyze Original
            status.write("Analyzing original score...")
            original_analysis = analyze_resume(client, resume_text, jd_text, model_choice)
            
            # 3. Generate New
            status.write("Optimizing resume...")
            optimized_resume = optimize_resume(client, resume_text, jd_text, model_choice)
            cover_letter = generate_cover_letter(client, resume_text, jd_text, model_choice)

            # 4. Analyze New
            status.write("Validating new score...")
            new_analysis = analyze_resume(client, optimized_resume, jd_text, model_choice)
            
            # 5. LOG TO ASTRA DB (Background Task)
            status.write("Saving transaction...")
            log_transaction_to_astra(
                original_text=resume_text,
                jd_text=jd_text,
                optimized_text=optimized_resume,
                scores={
                    "original": original_analysis['match_score'],
                    "new": new_analysis['match_score']
                }
            )

            status.update(label="Done!", state="complete", expanded=False)

            # 6. Display Results
            col1, col2 = st.columns(2)
            col1.metric("Original Score", f"{original_analysis['match_score']}%")
            col2.metric("New Score", f"{new_analysis['match_score']}%", delta=new_analysis['match_score']-original_analysis['match_score'])
            
            st.subheader("Optimized Resume")
            st.text_area("Copy this:", optimized_resume, height=400)
            
            # Download Buttons
            st.download_button("Download Resume", create_docx(optimized_resume), "Resume.docx")
            st.download_button("Download Cover Letter", create_docx(cover_letter), "CoverLetter.docx")

if __name__ == "__main__":
    main()
