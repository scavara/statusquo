# Simple HTML for the Admin Dashboard

LOGIN_HTML = """
<div style="text-align: center; margin-top: 50px; font-family: sans-serif;">
    <h1>🔐 Admin Access</h1>
    <p>Please log in with your Google Account to manage quotes.</p>
    <a href="/admin/google" style="background: #4285F4; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">Sign in with Google</a>
</div>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>StatusQuo Admin</title>
    </head>
<body>
    <div class="container">
        {% if not quotes %}
            {% else %}
            {% for q in quotes %}
            <div class="card">
                <div class="emoji-container">
                    {{ q.emoji }}
                </div>

                <div class="content">
                    <blockquote id="quote-{{ loop.index }}" class="quote-text">
                        </blockquote>

                    <div class="meta">
                        — <strong>{{ q.author }}</strong>
                        <span>|</span> Submitted by: <code>{{ q.proposer }}</code>
                    </div>

                    </div>
            </div>
            {% endfor %}
        {% endif %}
    </div>

    <script id="quote-data" type="application/json">
        {{ quotes | tojson }}
    </script>

    <script>
        const emojiConverter = new EmojiConvertor();
        emojiConverter.init_env();
        emojiConverter.replace_mode = 'unified';
        emojiConverter.allow_native = true;

        function cleanSlackMarkdown(text) {
            if (!text) return "";
            text = text.replace(/\*([^\*]+)\*/g, '$1');
            text = text.replace(/_([^_]+)_/g, '$1');
            text = text.replace(/~([^~]+)~/g, '$1');
            text = text.replace(/`([^`]+)`/g, '$1');
            return text;
        }

        document.addEventListener("DOMContentLoaded", function() {
            // 1. Load Data Securely
            const dataElement = document.getElementById('quote-data');
            // Handle case where no quotes exist
            const allQuotes = dataElement ? JSON.parse(dataElement.textContent) : [];

            // 2. Render content
            allQuotes.forEach((q, index) => {
                // Loop index in Jinja is 1-based
                const el = document.getElementById(`quote-${index + 1}`);
                if (el) {
                    // innerText prevents HTML injection (XSS)
                    el.innerText = cleanSlackMarkdown(q.text);
                }

                // Render Emoji (finding the sibling container)
                const card = el.closest('.card');
                const emojiContainer = card.querySelector('.emoji-container');
                if (emojiContainer) {
                    emojiContainer.innerHTML = emojiConverter.replace_colons(q.emoji);
                }
            });
        });
    </script>
</body>
</html>
"""
