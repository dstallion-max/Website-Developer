import os
import re
import shutil
import tempfile
import zipfile
from flask import Flask, request, jsonify
from flask_cors import CORS
from git import Repo
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Enhanced system prompt designed for realistic, self-contained standalone HTML
REALISTIC_DESIGN_SYSTEM_PROMPT = """
You are a Principal Frontend Engineer & UI/UX Director.
Your job is to produce a fully self-contained, high-fidelity, production-grade HTML5 file that looks like a live SaaS/E-commerce product when saved and opened locally in any browser.

DESIGN & ASSET RULES FOR A REAL-WORLD LOOK:
1. **No Broken/Generic Placeholders**: NEVER use via.placeholder.com or empty image containers.
2. **High-Quality Photography**: For product photos or hero imagery, use high-resolution, context-specific Unsplash URLs with explicit dimensions (e.g., `https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1200&q=80`).
3. **Standalone Visual Assets**: For icons, charts, diagrams, and abstract graphic backgrounds, render inline SVGs or CSS mesh gradients (`background: radial-gradient(...)`) so the page renders instantly offline without relying on external image hosts.
4. **Typography & Styling**: Embed Google Fonts (Inter, Plus Jakarta Sans, or Outfit) via `<link>` in the `<head>`. Include modern CSS variables, smooth box shadows (`box-shadow: 0 10px 30px -10px rgba(0,0,0,0.3)`), subtle borders (`border: 1px solid rgba(255,255,255,0.1)`), and dynamic hover states.
5. **Interactive UI State**: Include vanilla JavaScript to power interactive components (e.g., working mobile nav toggles, tab switching, interactive dropdowns, modal popups, chart toggles, and functional search filters).
6. **Realistic Micro-Copy**: Use actual, industry-specific headings, metric statistics ($124.5k ARR, 99.9% Uptime, +24% Growth), user reviews, and product features instead of generic 'Lorem Ipsum' text.

OUTPUT RULE:
Return ONLY valid HTML starting with <!DOCTYPE html>. Do NOT wrap in markdown code fences (```html ... ```).
"""

def extract_urls(text):
    if not text:
        return []
    url_pattern = r'https?://[^\s,"]+'
    return re.findall(url_pattern, text)

def extract_code_context(dir_path, max_chars=8000):
    context = ""
    for root, _, files in os.walk(dir_path):
        for file in files:
            if file.endswith(('.html', '.css', '.js', '.jsx', '.tsx')) and 'node_modules' not in root:
                try:
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        context += f"\n--- File: {file} ---\n{f.read(1500)}\n"
                except Exception:
                    continue
            if len(context) >= max_chars:
                break
        if len(context) >= max_chars:
            break
    return context[:max_chars]

def call_gemini(prompt, company_name, primary_color, secondary_color, repo_context="", current_code=""):
    if not GEMINI_API_KEY:
        return "<h3>Configuration Error</h3><p>GEMINI_API_KEY variable is missing.</p>"

    client = genai.Client(api_key=GEMINI_API_KEY)

    system_instruction = f"""
    {REALISTIC_DESIGN_SYSTEM_PROMPT}

    Brand Specs:
    - Project Name: {company_name}
    - Primary Color Theme: {primary_color}
    - Accent Color Theme: {secondary_color}

    STRICT EDITING RULE:
    If EXISTING GENERATED CODE is provided below, DO NOT replace the entire page from scratch. 
    Maintain the current page layout and design fidelity, applying only the requested additions or edits.
    """

    user_query = f"User Request: {prompt}\n"
    if current_code:
        user_query += f"\nEXISTING CODE TO UPDATE:\n{current_code}\n"
    if repo_context:
        user_query += f"\nRepository Context:\n{repo_context}"

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_query,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3
            )
        )
        return response.text.replace("```html", "").replace("```", "").strip()
    except Exception as e:
        return f"<h3>Gemini API Error</h3><pre>{str(e)}</pre>"

@app.route('/api/synthesize', methods=['POST'])
def synthesize():
    if request.content_type and 'multipart/form-data' in request.content_type:
        company_name = request.form.get('company_name', 'Brand')
        company_about = request.form.get('company_about', 'Web application')
        github_url = request.form.get('github_url', '').strip('[]"\' ')
        primary_color = request.form.get('primary_color', '#2563eb')
        secondary_color = request.form.get('secondary_color', '#38bdf8')
        current_code = request.form.get('current_code', '')
        uploaded_file = request.files.get('project_zip')
    else:
        data = request.json or {}
        company_name = data.get('company_name', 'Brand')
        company_about = data.get('company_about', 'Web application')
        github_url = str(data.get('github_url', '')).strip('[]"\' ')
        primary_color = data.get('primary_color', '#2563eb')
        secondary_color = data.get('secondary_color', '#38bdf8')
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
        print(f"Context extraction error: {e}")
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
        return jsonify({"success": False, "error": "GEMINI_API_KEY environment variable missing"}), 500

    company_name = request.form.get('company_name', 'Apex Studio')
    company_about = request.form.get('company_about', 'Synthesize provided design inputs.')
    primary_color = request.form.get('primary_color', '#6366f1')
    secondary_color = request.form.get('secondary_color', '#a855f7')
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
        print(f"Repo context error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    uploaded_images = request.files.getlist('reference_images')
    
    system_instruction = f"""
    {REALISTIC_DESIGN_SYSTEM_PROMPT}

    Brand Specs:
    - Project/Brand Name: {company_name}
    - Primary Color: {primary_color}
    - Secondary/Accent Color: {secondary_color}

    Provided References:
    - Reference Links: {', '.join(extracted_urls) if extracted_urls else 'None'}
    - Code Context: {'Included' if repo_context else 'None'}

    STRICT EDITING RULE:
    If EXISTING GENERATED CODE is provided below, DO NOT replace the entire page from scratch. 
    Maintain the current page layout and design fidelity, applying only the requested additions or edits.
    """

    contents = []
    user_prompt = f"User Directives:\n{company_about}\n"
    if current_code:
        user_prompt += f"\nEXISTING CODE TO UPDATE:\n{current_code}\n"
    if repo_context:
        user_prompt += f"\nRepo Context:\n{repo_context}\n"

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
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3
            )
        )
        generated_code = response.text.replace("```html", "").replace("```", "").strip()
        return jsonify({"success": True, "html_code": generated_code})
    except Exception as e:
        print(f"Design endpoint error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 Server active on http://127.0.0.1:5000")
    app.run(debug=True, port=5000)