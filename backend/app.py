import os
import re
import shutil
import tempfile
import time
import zipfile
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
from git import Repo
from google import genai
from google.genai import types

# Define absolute paths based on directory structure
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR)
CORS(app, resources={r"/api/*": {"origins": "*"}})

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# WORLD-CLASS DESIGN SYSTEM PROMPT (Ensures Stripe/Apple-grade output)
WORLD_CLASS_DESIGN_SYSTEM_PROMPT = """
You are a Staff Principal Frontend Engineer & Award-Winning Creative Director (ex-Stripe, ex-Apple).
Your objective is to generate pixel-perfect, hyper-modern, production-grade HTML5 pages that blow users away with clean aesthetics, flawless layout architecture, and rich interactivity.

DESIGN & ARCHITECTURE GUIDELINES:
1. **Design Aesthetics**:
   - Palette: Use modern CSS custom properties (`--primary`, `--accent`, `--surface`, `--text`).
   - Visual Polish: Apply glassmorphism (`backdrop-filter: blur(12px)`), refined dynamic shadows (`box-shadow: 0 20px 40px -15px rgba(0,0,0,0.08)`), subtle borders (`1px solid rgba(255,255,255,0.15)`), and smooth CSS transitions (`transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1)`).
   - Typography: Integrate Google Fonts ('Plus Jakarta Sans', 'Inter', or 'Outfit') with clear typographic hierarchy and balanced line heights.

2. **Zero Broken Assets**:
   - NEVER use `via.placeholder.com` or empty broken image blocks.
   - Images: Use high-res, specific Unsplash URLs with parameters (`auto=format&fit=crop&w=1200&q=80`).
   - Icons & Visuals: Render crisp inline SVGs, Lucide-style iconography, and CSS gradients (`background: radial-gradient(...)`).

3. **Production UX & Interactivity**:
   - Include complete, bug-free vanilla JavaScript for mobile navigation toggles, interactive tabbed interfaces, modal popups, drop-downs, and real-time UI state changes.
   - Use high-converting micro-copy, realistic business metrics ($4.8M ARR, 99.99% SLA, 150k Active Teams), customer testimonials, and realistic feature grids.

4. **COMPLETION & EFFICIENCY RULES**:
   - Write structured, DRY CSS and semantic HTML (Grid/Flexbox).
   - Do NOT omit sections or leave `<!-- Add rest of code here -->` comments.
   - ALWAYS return complete, valid HTML starting with `<!DOCTYPE html>` and ending cleanly with `</html>`.
   - Do NOT wrap response in markdown code blocks (` ```html `).
"""

# Static Route Handlers
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    if path != "" and os.path.exists(os.path.join(FRONTEND_DIR, path)):
        return send_from_directory(FRONTEND_DIR, path)
    return send_from_directory(FRONTEND_DIR, 'index.html')

@app.route('/designer')
def serve_designer():
    return send_from_directory(FRONTEND_DIR, 'designer.html')


def extract_urls(text):
    if not text:
        return []
    url_pattern = r'https?://[^\s,"]+'
    return re.findall(url_pattern, text)

def extract_code_context(dir_path, max_chars=3000):
    context = ""
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '__pycache__', 'coverage']]
        for file in files:
            if file.endswith(('.html', '.css', '.js', '.jsx', '.tsx')) and not file.endswith('.min.js'):
                try:
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        context += f"\n--- Context File: {file} ---\n{f.read(600)}\n"
                except Exception:
                    continue
            if len(context) >= max_chars:
                break
        if len(context) >= max_chars:
            break
    return context[:max_chars]

def generate_with_fallback(client, contents, system_instruction):
    """Executes call with backoff retries (503 handling) & maximum 8192 token limit."""
    models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash']
    
    for model in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        max_output_tokens=8192  # Full output capacity to prevent HTML truncation
                    )
                )
                html_text = response.text.replace("```html", "").replace("```", "").strip()
                return html_text
            except Exception as e:
                error_str = str(e)
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    time.sleep(2 * (attempt + 1))
                    continue
                elif attempt == 2:
                    break
                else:
                    raise e
    raise Exception("Design engine is under heavy traffic. Please resubmit in a few seconds.")

def call_gemini(prompt, company_name, primary_color, secondary_color, repo_context="", current_code=""):
    if not GEMINI_API_KEY:
        return "<h3>Configuration Error</h3><p>GEMINI_API_KEY environment variable is missing.</p>"

    client = genai.Client(api_key=GEMINI_API_KEY)

    system_instruction = f"""
    {WORLD_CLASS_DESIGN_SYSTEM_PROMPT}

    BRAND & SPECIFICATIONS:
    - Company / App Name: {company_name}
    - Primary Color Code: {primary_color}
    - Accent / Secondary Color: {secondary_color}

    PRECISION REVISION RULE:
    If existing HTML is provided, update and upgrade the page while preserving its structural intent. 
    Add missing requested components seamlessly without breaking existing styling.
    """

    user_query = f"Design Intent & Requirements: {prompt}\n"
    if current_code:
        user_query += f"\nEXISTING CODEBASE TO BUILD UPON:\n{current_code}\n"
    if repo_context:
        user_query += f"\nPROJECT REPOSITORY CONTEXT:\n{repo_context}"

    try:
        return generate_with_fallback(client, user_query, system_instruction)
    except Exception as e:
        return f"<h3>Engine Exception</h3><pre>{str(e)}</pre>"

@app.route('/api/synthesize', methods=['POST'])
def synthesize():
    if request.content_type and 'multipart/form-data' in request.content_type:
        company_name = request.form.get('company_name', 'Brand')
        company_about = request.form.get('company_about', 'Modern digital platform')
        github_url = request.form.get('github_url', '').strip('[]"\' ')
        primary_color = request.form.get('primary_color', '#0f172a')
        secondary_color = request.form.get('secondary_color', '#2563eb')
        current_code = request.form.get('current_code', '')
        uploaded_file = request.files.get('project_zip')
    else:
        data = request.json or {}
        company_name = data.get('company_name', 'Brand')
        company_about = data.get('company_about', 'Modern digital platform')
        github_url = str(data.get('github_url', '')).strip('[]"\' ')
        primary_color = data.get('primary_color', '#0f172a')
        secondary_color = data.get('secondary_color', '#2563eb')
        current_code = data.get('current_code', '')
        uploaded_file = None

    repo_context = ""
    temp_dir = tempfile.mkdtemp()

    try:
        if github_url:
            Repo.clone_from(github_url, temp_dir, depth=1)
            repo_context = extract_code_context(temp_dir)
        elif uploaded_file and uploaded_file.filename.endswith('.zip'):
            zip_path = os.path.join(temp_dir, 'upload.zip')
            uploaded_file.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            repo_context = extract_code_context(temp_dir)
    except Exception as e:
        print(f"Context extraction exception: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    generated_code = call_gemini(
        prompt=company_about,
        company_name=company_name,
        primary_color=primary_color,
        secondary_color=secondary_color,
        repo_context=repo_context,
        current_code=current_code
    )
    return jsonify({"success": True, "context_found": bool(repo_context), "html_code": generated_code})

@app.route('/api/fuse-design', methods=['POST'])
def fuse_design():
    if not GEMINI_API_KEY:
        return jsonify({"success": False, "error": "GEMINI_API_KEY variable missing"}), 500

    company_name = request.form.get('company_name', 'Nexus Systems')
    company_about = request.form.get('company_about', 'High-conversion SaaS layout')
    primary_color = request.form.get('primary_color', '#0f172a')
    secondary_color = request.form.get('secondary_color', '#6366f1')
    current_code = request.form.get('current_code', '')
    
    raw_links_text = request.form.get('raw_links', '')
    extracted_urls = extract_urls(raw_links_text)

    github_url = request.form.get('github_url', '').strip()
    uploaded_zip = request.files.get('project_zip')
    
    repo_context = ""
    temp_dir = tempfile.mkdtemp()

    try:
        if github_url:
            Repo.clone_from(github_url, temp_dir, depth=1)
            repo_context = extract_code_context(temp_dir)
        elif uploaded_zip and uploaded_zip.filename.endswith('.zip'):
            zip_path = os.path.join(temp_dir, 'upload.zip')
            uploaded_zip.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            repo_context = extract_code_context(temp_dir)
    except Exception as e:
        print(f"Repo context extraction error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    uploaded_images = request.files.getlist('reference_images')
    
    system_instruction = f"""
    {WORLD_CLASS_DESIGN_SYSTEM_PROMPT}

    BRAND SPECIFICATIONS:
    - Company Name: {company_name}
    - Primary Color: {primary_color}
    - Secondary Color: {secondary_color}

    CONTEXTUAL INPUTS:
    - Reference URLs: {', '.join(extracted_urls) if extracted_urls else 'None'}
    - Extract Status: {'Active' if repo_context else 'None'}

    PRECISION REVISION RULE:
    If existing HTML is provided, update and upgrade the page while preserving its structural intent.
    """

    contents = []
    user_prompt = f"Design Directives:\n{company_about}\n"
    if current_code:
        user_prompt += f"\nEXISTING HTML CODE:\n{current_code}\n"
    if repo_context:
        user_prompt += f"\nREPO CONTEXT:\n{repo_context}\n"

    contents.append(user_prompt)

    for img in uploaded_images:
        if img and img.filename:
            img_bytes = img.read()
            contents.append(
                types.Part.from_bytes(
                    data=img_bytes,
                    mime_type=img.content_type or 'image/png'
                )
            )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        generated_code = generate_with_fallback(client, contents, system_instruction)
        return jsonify({"success": True, "html_code": generated_code})
    except Exception as e:
        print(f"Fuse-design error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)