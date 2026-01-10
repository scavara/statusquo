# StatusQuo 🤖

**StatusQuo** is a serverless Slack bot that automates your profile status with witty quotes. It runs on a daily schedule to keep your status fresh and includes a "Human-in-the-Loop" approval workflow for adding new quotes to the database directly from Slack.

## 🚀 Features

* **📅 Auto-Scheduler:** Automatically updates your status (Emoji + Text) every day at 09:00 AM.
* **☁️ Cloud Native:** Fetches quotes from a serverless **AWS DynamoDB** table.
* **🛡️ Human-in-the-Loop:** Submit new quotes via Slack command (`/add-quote`). An admin must approve them via interactive buttons before they are saved to the database.
* **⚡ Socket Mode:** Secure connection without exposing public IP addresses.
* **👻 Ghost Writer:** Updates your status silently in the background using your personal User Token.

---

## 🛠️ Tech Stack

* **Language:** Python 3.10+
* **Framework:** [Slack Bolt](https://slack.dev/bolt-python/) (Socket Mode)
* **Cloud Data:** AWS DynamoDB (Boto3)
* **Scheduling:** APScheduler
* **Deployment:** Heroku (Worker Dyno)

---

## ⚙️ Prerequisites

* Python 3.8 or higher
* A Slack Workspace with permissions to create apps.
* An AWS Account (Free Tier is sufficient).
* **Slack App Tokens:**
    * `SLACK_BOT_TOKEN` (`xoxb-...`)
    * `SLACK_APP_TOKEN` (`xapp-...`)
    * `SLACK_USER_TOKEN` (`xoxp-...`)

---

## 📦 Installation & Local Setup

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/scavara/statusquo.git](https://github.com/scavara/statusquo.git)
    cd statusquo
    ```

2.  **Set up Virtual Environment**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**
    Create a `.env` file (DO NOT commit this to GitHub) and add your keys:
    ```ini
    SLACK_BOT_TOKEN=xoxb-your-token
    SLACK_APP_TOKEN=xapp-your-token
    SLACK_USER_TOKEN=xoxp-your-token
    AWS_ACCESS_KEY_ID=your-aws-key
    AWS_SECRET_ACCESS_KEY=your-aws-secret
    AWS_DEFAULT_REGION=us-east-1
    ```

5.  **Run Locally**
    ```bash
    python app.py
    ```

---

## ☁️ Deployment (Heroku)

1.  **Create App:** Create a new app on Heroku.
2.  **Config Vars:** Go to **Settings > Reveal Config Vars** and add all the variables listed in the setup above.
    * *Tip: Add `TZ` (e.g., `Europe/Berlin`) to set the scheduler timezone.*
3.  **Deploy:** Connect your GitHub repo and deploy the `main` branch.
4.  **Scale Worker:** Ensure the worker is running:
    ```bash
    heroku ps:scale worker=1
    ```

---

## 🎮 Usage

| Command | Description |
| :--- | :--- |
| `/quo` | **Manual Trigger:** Forces the bot to fetch a random quote and update your status immediately. |
| `/add-quote "Text" \| :emoji:` | **Submission:** Proposes a new quote. <br> *Example:* `/add-quote "Coding hard" | :computer:` |

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

> "Permission is hereby granted, free of charge, to any person obtaining a copy of this software..."

---

## 👤 Author

**[Your Name]**
* GitHub: [@scavara](https://github.com/scavara)
