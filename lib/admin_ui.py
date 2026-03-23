ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Admin Login - StatusQuo</title>
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
</head>
<body>
    <div style="text-align: center; margin-top: 50px; font-family: sans-serif;">
        <h1>🛡️ Admin Access</h1>
        <p>Restricted area. Please log in with your Admin Google Account.</p>
        <a href="/admin/login" style="background: #e74c3c; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">Admin Sign In</a>
    </div>
</body>
</html>
"""

USER_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Login - StatusQuo</title>
    <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
</head>
<body>
    <div style="text-align: center; margin-top: 50px; font-family: sans-serif;">
        <h1>👋 Welcome to StatusQuo</h1>
        <p>Sign in to submit your favorite quotes to the database.</p>
        <a href="/user/login" style="background: #4285F4; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">Sign in with Google</a>
    </div>
</body>
</html>
"""

USER_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Dashboard - StatusQuo</title>
    <link rel="icon" type="image/x-icon" href="{{ url_for('static', filename='favicon.ico') }}">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.min.css">
    <style>
        body { padding: 40px; background-color: #f4f5f6; }
        .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .flashes { list-style-type: none; padding: 0; }
        .flashes li { background: #e0f2fe; color: #0369a1; padding: 10px; border-radius: 5px; margin-bottom: 15px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>👋 Welcome, {{ user.name }}</h1>
        <p><a href="/user/logout">Logout</a></p>
        <hr>
        
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            <ul class="flashes">
            {% for message in messages %}
              <li>{{ message }}</li>
            {% endfor %}
            </ul>
          {% endif %}
        {% endwith %}

        <h3>➕ Submit a New Quote</h3>
        <form action="/dashboard/add" method="post">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
            <label>Quote Text</label>
            <textarea name="text" required maxlength="80"></textarea>
            <label>Author</label>
            <input type="text" name="author" required maxlength="20">
            <label>Emoji (e.g., :wave:)</label>
            <input type="text" name="emoji" required placeholder=":smile:">
            <button type="submit" class="button button-primary">Submit for Review</button>
        </form>
    </div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>StatusQuo Admin</title>
    <link rel="icon" type="image/x-icon" href="{{ url_for('static', filename='favicon.ico') }}">
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
            align-items: center; 
            gap: 20px;
        }

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
                <div class="emoji-container" data-emoji="{{ q.emoji }}">
                    {{ q.emoji }}
                </div>
                
                <div class="content">
                    <blockquote class="quote-text" data-text="{{ q.text }}">
                        {{ q.text }}
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

    <script>
        const emojiConverter = new EmojiConvertor();
        emojiConverter.init_env();
        emojiConverter.replace_mode = 'unified'; 
        emojiConverter.allow_native = true;

        function cleanSlackMarkdown(text) {
            if (!text) return "";
            text = text.replace(/\\*([^\\*]+)\\*/g, '$1');
            text = text.replace(/_([^_]+)_/g, '$1');
            text = text.replace(/~([^~]+)~/g, '$1');
            text = text.replace(/`([^`]+)`/g, '$1');
            return text;
        }

        document.addEventListener("DOMContentLoaded", function() {
            document.querySelectorAll('.emoji-container').forEach(el => {
                const rawEmoji = el.getAttribute('data-emoji');
                el.innerHTML = emojiConverter.replace_colons(rawEmoji);
            });

            document.querySelectorAll('.quote-text').forEach(el => {
                const rawText = el.getAttribute('data-text');
                el.innerText = cleanSlackMarkdown(rawText);
            });
        });
    </script>
</body>
</html>
"""
