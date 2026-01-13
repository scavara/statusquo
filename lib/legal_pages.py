# Simple HTML templates for your legal pages

PRIVACY_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Privacy Policy - StatusQuo</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }
        h1 { color: #2c3e50; }
        h2 { color: #34495e; border-bottom: 2px solid #eee; padding-bottom: 10px; margin-top: 30px; }
        a { color: #3498db; text-decoration: none; }
        .footer { margin-top: 50px; font-size: 0.9em; color: #7f8c8d; border-top: 1px solid #eee; padding-top: 20px; }
    </style>
</head>
<body>
    <h1>Privacy Policy</h1>
    <p><strong>Last Updated:</strong> January 2026</p>

    <h2>1. Data We Collect</h2>
    <p>StatusQuo ("the App") collects the minimum amount of data required to function:</p>
    <ul>
        <li><strong>Slack User IDs & Team IDs:</strong> To identify who to update.</li>
        <li><strong>OAuth Access Tokens:</strong> Stored securely to perform status updates on your behalf.</li>
        <li><strong>Custom Quotes:</strong> Any text you submit via the App.</li>
    </ul>

    <h2>2. How We Use Data</h2>
    <ul>
        <li><strong>Status Updates:</strong> We use your User Token solely to update your profile status and check token validity.</li>
        <li><strong>Storage:</strong> Tokens are encrypted at rest using AWS DynamoDB.</li>
    </ul>

    <h2>3. Data Sharing</h2>
    <p>We do not sell, trade, or otherwise transfer your personally identifiable information to outside parties.</p>

    <div class="footer">
        <p>&copy; 2026 StatusQuo. <a href="/">Back to Home</a></p>
    </div>
</body>
</html>
"""

SUPPORT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Support - StatusQuo</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; }
        h1 { color: #2c3e50; }
        h2 { color: #34495e; }
        .button { display: inline-block; background: #27ae60; color: white; padding: 10px 20px; border-radius: 5px; margin-top: 10px; }
    </style>
</head>
<body>
    <h1>Support Center</h1>
    <p>Having trouble with StatusQuo? We're here to help!</p>

    <h2>🐛 Common Issues</h2>
    <ul>
        <li><strong>Bot stopped updating?</strong> If you changed your Slack password, your token was revoked. Please reinstall the app.</li>
        <li><strong>Quotes not saving?</strong> Ensure you have approved them in the messages tab.</li>
    </ul>

    <h2>✉️ Contact Us</h2>
    <p>For direct support or privacy inquiries, please email us:</p>
    <p><strong>support@statusquo.bot</strong> (Replace with your real email)</p>

    <div style="margin-top: 40px;">
        <a href="/" class="button">Back to Home</a>
    </div>
</body>
</html>
"""

INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>StatusQuo Bot</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; text-align: center; padding: 50px; color: #333; }
        h1 { font-size: 2.5em; margin-bottom: 10px; }
        p { font-size: 1.2em; color: #666; }
        .btn { display: inline-block; background-color: #4A154B; color: white; padding: 15px 30px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 1.1em; margin: 20px 0; }
        .links { margin-top: 30px; font-size: 0.9em; }
        .links a { color: #666; margin: 0 10px; text-decoration: none; }
        .links a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>🤖 StatusQuo</h1>
    <p>The witty, automated status updater for Slack.</p>
    
    <a href="/slack/install" class="btn">Add to Slack</a>
    
    <div class="links">
        <a href="/privacy">Privacy Policy</a> | 
        <a href="/support">Support</a> | 
        <a href="https://github.com/scavara/statusquo">GitHub (Private)</a>
    </div>
</body>
</html>
"""
