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

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR)
CORS(app, resources={r"/api/*": {"origins": "*"}})

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

UNIVERSAL_DESIGN_SYSTEM_PROMPT = """
You are an expert Principal Frontend Engineer and UI/UX Architect capable of building ANY website, dashboard, or application requested.

CORE EXECUTION GUIDELINES:
1. **Dynamic Styling & Palette Control**:
   - Honor the exact user-specified primary and accent colors if provided.
   - If colors are unspecified, dynamically synthesize a modern color scheme (CSS variables: `--primary`, `--accent`, `--surface`, `--bg`, `--text`).
   - Apply dynamic CSS features: glassmorphism (`backdrop-filter`), CSS Grid/Flexbox layouts, hover micro-interactions, and box-shadows.

2. **Tailwind CSS & External Asset Efficiency**:
   - Use CDN utilities (e.g. `<script src="https://cdn.tailwindcss.com"></script>`) so code remains lightweight and never truncates due to CSS verbosity.
   - Never use broken placeholder images. Use dynamic high-resolution Unsplash URLs and inline SVGs.

3. **Complete Production Output**:
   - Always output fully functional, complete HTML with working Vanilla JavaScript for menus, tabs, modals, and interactivity.
   - The document MUST end with valid closing tags: `</body></html>`. Do NOT wrap response in markdown code blocks (` ```html `).
"""

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

def extract_code_context(dir_path, max_chars=4000):
    context = ""
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', 'dist', 'build', '__pycache__', 'coverage']]
        for file in files:
            if file.endswith(('.html', '.css', '.js', '.jsx', '.tsx')) and not file.endswith('.min.js'):
                try:
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        context += f"\n--- Context File: {file} ---\n{f.read(800)}\n"
                except Exception:
                    continue
            if len(context) >= max_chars:
                break
        if len(context) >= max_chars:
            break
    return context[:max_chars]

def generate_robust_code(client, contents, system_instruction):
    """Fallback engine designed to seamlessly route around 429 quota exhaustion limits."""
    # Ordered by preference, falling back to models with higher free limits or legacy stability
    models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.5-flash']
    
    last_error = ""
    for model in models_to_try:
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.3,
                    max_output_tokens=8192
                )
            )
            html_text = response.text.replace("```html", "").replace("```", "").strip()
            
            # Auto-continuation if cut off
            if not html_text.endswith("</html>"):
                continuation_prompt = [
                    f"Here is partial HTML code that was cut off mid-generation:\n\n{html_text[-3000:]}\n\n"
                    "CONTINUE EXACTLY from where it was cut off. Complete all remaining markup, scripts, and close with </body></html>."
                ]
                cont_response = client.models.generate_content(
                    model=model,
                    contents=continuation_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        max_output_tokens=4096
                    )
                )
                cont_text = cont_response.text.replace("```html", "").replace("```", "").strip()
                html_text += cont_text

            return html_text

        except Exception as e:
            error_str = str(e)
            last_error = error_str
            # If 429 Quota Exhausted, immediately switch to next model in list
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                print(f"Quota exhausted for model {model}. Auto-switching to next available model...")
                continue
            elif "503" in error_str or "UNAVAILABLE" in error_str:
                time.sleep(2)
                continue
            else:
                continue

    raise Exception(f"All model quotas temporarily busy. Last Error: {last_error}")

def call_gemini(prompt, company_name, primary_color, secondary_color, repo_context="", current_code=""):
    if not GEMINI_API_KEY:
        return "<h3>Configuration Error</h3><p>GEMINI_API_KEY environment variable is missing.</p>"

    client = genai.Client(api_key=GEMINI_API_KEY)

    color_instruction = ""
    if primary_color or secondary_color:
        color_instruction = f"USER COLOR PREFERENCES: Primary Color: {primary_color or 'Auto'}, Accent/Secondary Color: {secondary_color or 'Auto'}"
    else:
        color_instruction = "COLOR INSTRUCTION: Automatically choose a high-converting palette suited for the project intent."

    system_instruction = f"""
    {UNIVERSAL_DESIGN_SYSTEM_PROMPT}

    BRAND & CONTEXT:
    - App/Site Name: {company_name or 'Auto-Detect / Versatile App'}
    - {color_instruction}

    REVISION RULE:
    If existing code is provided, upgrade visual structure and resolve missing sections without discarding core logic.
    """

    user_query = f"User Instructions & Requirements: {prompt}\n"
    if current_code:
        user_query += f"\nEXISTING CODEBASE TO BUILD UPON:\n{current_code}\n"
    if repo_context:
        user_query += f"\nATTACHED REPOSITORY CONTEXT:\n{repo_context}"

    try:
        return generate_robust_code(client, user_query, system_instruction)
    except Exception as e:
        return f"<h3>Engine Exception</h3><pre>{str(e)}</pre>"

@app.route('/api/synthesize', methods=['POST'])
def synthesize():
    if request.content_type and 'multipart/form-data' in request.content_type:
        company_name = request.form.get('company_name', '')
        company_about = request.form.get('company_about', 'Build a modern web application')
        github_url = request.form.get('github_url', '').strip('[]"\' ')
        primary_color = request.form.get('primary_color', '')
        secondary_color = request.form.get('secondary_color', '')
        current_code = request.form.get('current_code', '')
        uploaded_file = request.files.get('project_zip')
    else:
        data = request.json or {}
        company_name = data.get('company_name', '')
        company_about = data.get('company_about', 'Build a modern web application')
        github_url = str(data.get('github_url', '')).strip('[]"\' ')
        primary_color = data.get('primary_color', '')
        secondary_color = data.get('secondary_color', '')
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
        print(f"Context extraction note: {e}")
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

    company_name = request.form.get('company_name', '')
    company_about = request.form.get('company_about', 'Modern web layout')
    primary_color = request.form.get('primary_color', '')
    secondary_color = request.form.get('secondary_color', '')
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
    
    color_instruction = ""
    if primary_color or secondary_color:
        color_instruction = f"USER COLORS: Primary: {primary_color or 'Auto'}, Secondary: {secondary_color or 'Auto'}"
    else:
        color_instruction = "COLOR INSTRUCTION: Automatically pick optimal visual colors for the design."

    system_instruction = f"""
    {UNIVERSAL_DESIGN_SYSTEM_PROMPT}

    BRAND SPECIFICATIONS:
    - Site Title: {company_name or 'Dynamic Project'}
    - {color_instruction}
    - Reference Links: {', '.join(extracted_urls) if extracted_urls else 'None'}
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
        generated_code = generate_robust_code(client, contents, system_instruction)
        return jsonify({"success": True, "html_code": generated_code})
    except Exception as e:
        print(f"Fuse-design error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/stream-build', methods=['POST'])
def stream_build():
    data = request.json or {}
    company_about = data.get('prompt', 'Build a modern web application')
    company_name = data.get('company_name', '')
    primary_color = data.get('primary_color', '')
    secondary_color = data.get('secondary_color', '')
    current_code = data.get('current_code', '')

    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY environment variable missing"}), 500

    client = genai.Client(api_key=GEMINI_API_KEY)

    system_instruction = f"""
    {UNIVERSAL_DESIGN_SYSTEM_PROMPT}
    - Company Name: {company_name or 'Dynamic Platform'}
    - Custom Primary: {primary_color or 'Auto-Detect'}
    - Custom Secondary: {secondary_color or 'Auto-Detect'}
    """

    user_query = f"Requirements: {company_about}\n"
    if current_code:
        user_query += f"\nEXISTING CODE:\n{current_code}\n"

    def generate_stream():
        models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.5-flash']
        for model in models_to_try:
            try:
                response_stream = client.models.generate_content_stream(
                    model=model,
                    contents=user_query,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3,
                        max_output_tokens=8192
                    )
                )
                for chunk in response_stream:
                    if chunk.text:
                        cleaned_chunk = chunk.text.replace("```html", "").replace("```", "")
                        yield cleaned_chunk
                break
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    continue
                else:
                    yield f"<!-- Error streaming content: {error_str} -->"
                    break

    return Response(stream_with_context(generate_stream()), content_type='text/plain')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)