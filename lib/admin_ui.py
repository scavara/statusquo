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
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
    <script src="https://cdn.jsdelivr.net/npm/emoji-js@3.6.0/lib/emoji.min.js"></script>
    
    <style>
        body { padding: 40px; background-color: #f4f5f6; }
        .container { max-width: 900px; margin: 0 auto; }
        
        .card { 
            background: white;
            border: 1px solid #e1e1e1; 
            padding: 20px; 
            margin-bottom: 20px; 
            border-radius: 8px; 
            box-shadow: 0 2px 5px rgba(0,0,0,0.05); 
            display: flex; 
            align-items: center; /* Vertically center content */
            gap: 20px;
        }

        /* Fixed width for emoji to prevent overlap */
        .emoji-container { 
            font-size: 3em; 
            min-width: 80px; 
            text-align: center;
            flex-shrink: 0;
        }

        .content { flex-grow: 1; }
        
        blockquote { 
            border-left: 0.3rem solid #9b4dca; 
            margin-left: 0; 
            margin-right: 0;
            background-color: #fafafa;
            padding: 10px 15px;
        }
        
        .meta { color: #606c76; font-size: 0.9em; margin-top: 5px; }
        
        .actions { margin-top: 15px; display: flex; gap: 10px; }
        
        form { margin-bottom: 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ Moderation Queue</h1>
        <p>Logged in as: <strong>{{ user.name }}</strong> | <a href="/admin/logout">Logout</a></p>
        <hr>
        
        {% if not quotes %}
            <div class="card" style="justify-content: center; padding: 40px;">
                <h3>✅ All caught up! No pending quotes.</h3>
            </div>
        {% else %}
            {% for q in quotes %}
            <div class="card">
                <div class="emoji-container" id="emoji-{{ loop.index }}">
                    {{ q.emoji }}
                </div>
                
                <div class="content">
                    <blockquote class="quote-text" id="quote-{{ loop.index }}">
                        Loading...
                    </blockquote>
                    
                    <div class="meta">
                        — <strong>{{ q.author }}</strong> 
                        <span style="color: #ccc;">|</span> 
                        Submitted by: <code>{{ q.proposer }}</code>
                    </div>
                    
                    <div class="actions">
                        <form action="/admin/approve/{{ q.quote_id }}" method="post">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                            <button type="submit" class="button button-primary">Approve</button>
                        </form>
                        <form action="/admin/deny/{{ q.quote_id }}" method="post">
                            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
                            <button type="submit" class="button button-clear" style="color: red;">Deny</button>
                        </form>
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
        // Initialize Emoji Converter
        const emojiConverter = new EmojiConvertor();
        emojiConverter.init_env();
        emojiConverter.replace_mode = 'unified'; // Render as Unicode characters
        emojiConverter.allow_native = true;

        // Strip Slack Markdown chars (*bold*, _italic_, etc)
        function cleanSlackMarkdown(text) {
            if (!text) return "";
            // Remove stars used for bold: *word* -> word
            text = text.replace(/\*([^\*]+)\*/g, '$1');
            // Remove underscores used for italics: _word_ -> word
            text = text.replace(/_([^_]+)_/g, '$1');
            // Remove tildes used for strikethrough: ~word~ -> word
            text = text.replace(/~([^~]+)~/g, '$1');
            // Remove backticks used for code: `word` -> word
            text = text.replace(/`([^`]+)`/g, '$1');
            return text;
        }

        document.addEventListener("DOMContentLoaded", function() {
            // 1. Get Data Securely
            const dataScript = document.getElementById('quote-data');
            const allQuotes = dataScript ? JSON.parse(dataScript.textContent) : [];

            // 2. Render content safely
            allQuotes.forEach((q, index) => {
                // Jinja loop.index is 1-based, matching our IDs
                const i = index + 1;
                
                // Update Text (innerText prevents HTML injection)
                const textEl = document.getElementById('quote-' + i);
                if (textEl) {
                    textEl.innerText = cleanSlackMarkdown(q.text);
                }
                
                // Update Emoji
                const emojiEl = document.getElementById('emoji-' + i);
                if (emojiEl) {
                    emojiEl.innerHTML = emojiConverter.replace_colons(q.emoji);
                }
            });
        });
    </script>
</body>
</html>
"""
