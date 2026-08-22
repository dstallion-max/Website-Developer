document.addEventListener('DOMContentLoaded', () => {
    // Screen Resolution Guard (Laptop / Desktop Only)
    function isDesktopViewport() {
        return window.innerWidth >= 1024;
    }

    // Color Pickers & Hex Sync
    const colorPairs = [
        { picker: 'primary-color', hex: 'primary-hex', swatch: 'primary-swatch' },
        { picker: 'secondary-color', hex: 'accent-hex', swatch: 'accent-swatch' }
    ];

    colorPairs.forEach(({ picker, hex, swatch }) => {
        const pickerEl = document.getElementById(picker);
        const hexEl = document.getElementById(hex);
        const swatchEl = document.getElementById(swatch);

        if (pickerEl && hexEl && swatchEl) {
            swatchEl.style.backgroundColor = pickerEl.value;

            pickerEl.addEventListener('input', (e) => {
                const val = e.target.value;
                hexEl.value = val;
                swatchEl.style.backgroundColor = val;
            });

            hexEl.addEventListener('input', (e) => {
                let val = e.target.value.trim();
                if (!val.startsWith('#')) val = '#' + val;
                if (/^#[0-9A-F]{6}$/i.test(val)) {
                    pickerEl.value = val;
                    swatchEl.style.backgroundColor = val;
                }
            });
        }
    });

    const form = document.getElementById('designer-form');
    const statusBox = document.getElementById('status-message');
    const previewFrame = document.getElementById('preview-frame');
    const codeOutput = document.getElementById('code-output');
    const copyBtn = document.getElementById('copy-code-btn');
    const downloadBtn = document.getElementById('download-btn');
    const resetBtn = document.getElementById('reset-btn');
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    // Tab Switching
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(`${btn.dataset.tab}-tab`).classList.add('active');
        });
    });

    // Reset Handler
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            codeOutput.textContent = '';
            const doc = previewFrame.contentWindow.document;
            doc.open();
            doc.write('<html><body style="background:#0f172a; color:#94a3b8; font-family:sans-serif; display:flex; align-items:center; justify-content:center; height:100vh;">Ready for your design inputs...</body></html>');
            doc.close();

            document.getElementById('fusion-prompt').value = '';
            
            const rawLinksInput = document.getElementById('raw-links');
            if (rawLinksInput) rawLinksInput.value = '';
            
            const repoUrlInput = document.getElementById('github-url');
            if (repoUrlInput) repoUrlInput.value = '';

            const zipInput = document.getElementById('project-zip');
            if (zipInput) zipInput.value = '';

            const imgInput = document.getElementById('design-images');
            if (imgInput) imgInput.value = '';

            showStatus('🧹 Workspace reset. Ready for a new prompt!', 'info');
        });
    }

    // Form Submit Handler
    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        if (!isDesktopViewport()) {
            showStatus('⚠️ Designer Studio requires a desktop view (min-width: 1024px).', 'error');
            return;
        }

        const formData = new FormData();
        formData.append('company_name', document.getElementById('company-name')?.value || 'Apex Studio');
        formData.append('company_about', document.getElementById('fusion-prompt').value);
        formData.append('primary_color', document.getElementById('primary-color').value);
        formData.append('secondary_color', document.getElementById('secondary-color').value);

        // Optional GitHub Repo
        const repoUrl = document.getElementById('github-url') ? document.getElementById('github-url').value : '';
        if (repoUrl.trim()) {
            formData.append('github_url', repoUrl.trim());
        }

        // Raw Links Parsing
        const rawLinks = document.getElementById('raw-links') ? document.getElementById('raw-links').value : '';
        if (rawLinks.trim()) {
            formData.append('raw_links', rawLinks.trim());
        }

        // Optional Reference Screenshots / UI Images
        const imageInput = document.getElementById('design-images');
        if (imageInput && imageInput.files.length > 0) {
            for (let i = 0; i < imageInput.files.length; i++) {
                formData.append('reference_images', imageInput.files[i]);
            }
        }

        // Optional Code ZIP File
        const zipInput = document.getElementById('project-zip');
        if (zipInput && zipInput.files.length > 0) {
            formData.append('project_zip', zipInput.files[0]);
        }

        // Preserve current code for targeted edits
        const existingCode = codeOutput.textContent || '';
        if (existingCode.trim().length > 0) {
            formData.append('current_code', existingCode);
        }

        showStatus('🧠 Processing inputs and generating design...', 'info');

        try {
            const response = await fetch('http://127.0.0.1:5000/api/fuse-design', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                const doc = previewFrame.contentWindow.document;
                doc.open();
                doc.write(result.html_code);
                doc.close();

                codeOutput.textContent = result.html_code;
                showStatus('✨ Design generated successfully!', 'success');
            } else {
                showStatus(`❌ Generation failed: ${result.error || 'Unknown error'}`, 'error');
            }
        } catch (err) {
            console.error(err);
            showStatus('❌ Backend connection error. Ensure python backend/app.py is running!', 'error');
        }
    });

    // Copy Code Handler
    copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(codeOutput.textContent).then(() => {
            copyBtn.textContent = '✅ Copied!';
            setTimeout(() => { copyBtn.textContent = '📋 Copy Code'; }, 2000);
        });
    });

    // Download HTML Handler
    downloadBtn.addEventListener('click', () => {
        const code = codeOutput.textContent;
        if (!code || code.trim().length === 0) {
            showStatus('⚠️ No code available to download.', 'error');
            return;
        }

        const name = document.getElementById('company-name')?.value || 'fused-design';
        const fileName = `${name.toLowerCase().replace(/[^a-z0-9]/g, '-')}.html`;

        const blob = new Blob([code], { type: 'text/html' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);

        showStatus(`💾 Saved output as ${fileName}`, 'success');
    });

    function showStatus(msg, type) {
        statusBox.textContent = msg;
        statusBox.className = `status-box ${type}`;
        statusBox.classList.remove('hidden');
    }
});