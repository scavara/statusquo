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
    <style>
        body { padding: 40px; }
        .card { border: 1px solid #eee; padding: 20px; margin-bottom: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
        .emoji { font-size: 2em; }
        .actions { margin-top: 15px; }
    </style>
</head>
<body>
    <h1>🛡️ Moderation Queue</h1>
    <p>Logged in as: <strong>{{ user.name }}</strong> | <a href="/admin/logout">Logout</a></p>
    <hr>
    
    {% if not quotes %}
        <p>✅ All caught up! No pending quotes.</p>
    {% else %}
        {% for q in quotes %}
        <div class="card">
            <div class="row">
                <div class="column column-10"><span class="emoji">{{ q.emoji }}</span></div>
                <div class="column column-90">
                    <blockquote>{{ q.text }}</blockquote>
                    <p><em>— {{ q.author }}</em> <small>(Submitted by: {{ q.proposer }})</small></p>
                    
                    <div class="actions">
                        <form action="/admin/approve/{{ q.quote_id }}" method="post" style="display:inline;">
                            <button type="submit" class="button button-primary">Approve</button>
                        </form>
                        <form action="/admin/deny/{{ q.quote_id }}" method="post" style="display:inline;">
                            <button type="submit" class="button button-clear" style="color: red;">Deny</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
    {% endif %}
</body>
</html>
"""
