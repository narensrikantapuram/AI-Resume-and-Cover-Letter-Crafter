import streamlit as st
import openai
import pdfplumber
import docx
from io import BytesIO
import json

# --- CONFIGURATION ---
st.set_page_config(page_title="AI Resume Architect", layout="wide")

# --- HELPER FUNCTIONS: TEXT EXTRACTION ---

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

# --- AI LOGIC ---

def analyze_resume(client, resume_text, jd_text, model="gpt-4o"):
    """
    Analyzes the resume against the JD and returns a JSON object 
    with a match score and improvement tips.
    """
    prompt = f"""
    Act as a strict ATS (Applicant Tracking System). 
    Compare the Resume against the Job Description.

    CRITERIA FOR SCORING:
    1. Exact Keyword Matching (Do the skills in JD appear in Resume?)
    2. Job Title Relevance
    3. Measurable Results (Numbers/%)
    
    TASK:
    Return a JSON object with:
    - "match_score": A number between 0-100.
    - "tips": An array of 3 strings indicating missing keywords or weak areas.

    RESUME: {resume_text[:3000]}
    JD: {jd_text[:1500]}
    """
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a strict ATS algorithm. Output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        response_format={ "type": "json_object" },
        temperature=0.2
    )
    return json.loads(response.choices[0].message.content)

def optimize_resume(client, resume_text, jd_text, model="gpt-4o"):
    prompt = f"""
    You are an expert Resume Writer specializing in beating ATS algorithms.
    Your goal is to rewrite the provided resume to get a 95% match score against the Job Description.

    INSTRUCTIONS:
    1. **Keyword Mirroring**: Identify hard skills and keywords in the JD. Use the EXACT SAME PHRASING in the resume.
    2. **Summary**: Rewrite the Professional Summary to be a 3-sentence pitch directly addressing the JD's top requirements.
    3. **Experience**: Keep the user's actual companies and dates. Rewrite the bullet points to emphasize results using keywords from the JD.
    4. **Skills Section**: Create a dedicated "Technical Skills" or "Core Competencies" section. Fill it with matching skills from the JD that the candidate possesses.
    5. **Honesty**: Do not invent jobs. If a skill is strictly missing, do not lie, but emphasize adjacent skills.
    
    FORMAT: 
    Clean text format suitable for copy-pasting into Word. No markdown bolding (**), just plain text with bullet points (-).

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
    prompt = f"""
    Write a compelling cover letter for this job.
    
    GUIDELINES:
    1. Tone: Enthusiastic, Professional, Direct.
    2. Hook: Start with why the candidate fits the specific role title in the JD.
    3. Body: Highlight 3 key achievements from the resume that solve problems listed in the JD.
    4. Call to Action: Request an interview.
    
    RESUME: {resume_text}
    JD: {jd_text}
    """
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content

# --- MAIN UI ---

def main():
    # Title and Header
    st.title("🚀 AI Resume Architect")
    st.markdown("""
    <div style="background-color: #f0f2f6; padding: 10px; border-radius: 10px; margin-bottom: 20px;">
        <strong>ATS-Optimized Mode:</strong> This tool analyzes your resume, calculates the match score, 
        and rewrites it to target specific keywords in the Job Description.
    </div>
    """, unsafe_allow_html=True)

    # Sidebar Config
    with st.sidebar:
        st.header("🔑 Configuration")
        api_key = st.text_input("OpenAI API Key", type="password", help="Get your key from platform.openai.com")
        model_choice = st.selectbox("Model", ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"])
        st.caption("Note: GPT-4o is recommended for best ATS results.")

    # Initialize Session State for storing results
    if 'results' not in st.session_state:
        st.session_state.results = None

    # Input Section
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. Upload Resume")
        uploaded_file = st.file_uploader("PDF or DOCX", type=["pdf", "docx"])

    with col2:
        st.subheader("2. Job Description")
        jd_text = st.text_area("Paste the JD here", height=200)

    # Generate Button
    if st.button("Generate Resume & Cover Letter", type="primary"):
        if not api_key:
            st.error("Please enter your OpenAI API Key in the sidebar.")
            return
        if not uploaded_file or not jd_text:
            st.error("Please upload a resume and provide a job description.")
            return

        client = openai.OpenAI(api_key=api_key)
        
        # Processing Steps
        with st.status("🤖 AI Architect is working...", expanded=True) as status:
            
            # 1. Text Extraction
            status.write("Reading document...")
            if uploaded_file.name.endswith(".pdf"):
                resume_text = extract_text_from_pdf(uploaded_file)
            else:
                resume_text = extract_text_from_docx(uploaded_file)

            # 2. Original Analysis
            status.write("Analyzing original match score...")
            original_analysis = analyze_resume(client, resume_text, jd_text, model_choice)
            
            # 3. Generation
            status.write("Rewriting resume for ATS optimization...")
            optimized_resume = optimize_resume(client, resume_text, jd_text, model_choice)
            
            status.write("Drafting cover letter...")
            cover_letter = generate_cover_letter(client, resume_text, jd_text, model_choice)

            # 4. Final Analysis (Verify new score)
            status.write("Verifying new match score...")
            new_analysis = analyze_resume(client, optimized_resume, jd_text, model_choice)
            
            status.update(label="✅ Processing Complete!", state="complete", expanded=False)

            # Store results in session state
            st.session_state.results = {
                "original_score": original_analysis['match_score'],
                "original_tips": original_analysis['tips'],
                "new_score": new_analysis['match_score'],
                "optimized_resume": optimized_resume,
                "cover_letter": cover_letter
            }

    # --- RESULTS DISPLAY ---
    if st.session_state.results:
        res = st.session_state.results
        
        st.divider()
        
        # Scoreboard
        c1, c2, c3 = st.columns([1, 1, 2])
        
        with c1:
            st.metric(label="Original Match", value=f"{res['original_score']}%")
        
        with c2:
            st.metric(label="Optimized Match", value=f"{res['new_score']}%", delta=f"{res['new_score'] - res['original_score']}%")

        with c3:
            st.info(f"**Improvement Tips:**\n\n" + "\n".join([f"- {tip}" for tip in res['original_tips']]))

        st.divider()

        # Document Tabs
        tab1, tab2 = st.tabs(["📄 Optimized Resume", "✉️ Cover Letter"])
        
        with tab1:
            st.text_area("Resume Preview", res['optimized_resume'], height=500)
            st.download_button(
                label="Download Resume (.docx)",
                data=create_docx(res['optimized_resume']),
                file_name="Optimized_Resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            
        with tab2:
            st.text_area("Cover Letter Preview", res['cover_letter'], height=500)
            st.download_button(
                label="Download Cover Letter (.docx)",
                data=create_docx(res['cover_letter']),
                file_name="Cover_Letter.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )

if __name__ == "__main__":
    main()