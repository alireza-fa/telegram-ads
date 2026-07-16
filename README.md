# Telegram Marketing Automation Platform

A robust, asynchronous, and scalable Telegram cold outreach and marketing automation system built with Django, Celery, and Telethon. This platform allows you to scrape target audiences from Telegram groups/channels and run sequential, anti-spam marketing campaigns using multiple rotating accounts.

## 🚀 Features
* **Smart Crawler:** Scrapes users from group histories or channel comments while respecting rate limits.
* **Campaign Sender:** Sends sequential message chains (Text & Voice Notes) to targeted users.
* **Account Rotation & Connection Pooling:** Rotates multiple Telegram accounts to bypass rate limits and maintains active TCP connections to prevent DDOS flags.
* **Anti-Spam Voice Notes:** Automatically caches Voice Notes (`.ogg` with OPUS codec) in "Saved Messages" to reuse `file_id`s and prevent upload-based spam bans.
* **Admin-Driven Workflow:** Fully manageable via the Django Admin interface.

---

## 🛠 Prerequisites

* **Python:** `3.13`
* **Docker & Docker Compose:** Required to run the backing services (PostgreSQL & Redis).

---

## ⚙️ Installation & Setup

**1. Clone the repository and navigate to the project directory:**
```bash
git clone <repository_url>
cd <project_directory>

```

**2. Configure Environment Variables:**
Copy the provided example environment file. You can leave the default values for local development or adjust them as needed.

```bash
cp .env.example .env

```

**3. Start Backing Services (Database & Redis):**
The project uses Docker Compose to spin up PostgreSQL (with pgvector) and Redis (used as the Celery broker). Start them in the background:

```bash
docker compose up -d

```

**4. Create and activate a virtual environment:**

```bash
python3.13 -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate

```

**5. Install dependencies:**

```bash
pip install -r requirements.txt

```

**6. Run database migrations:**
*(Ensure your Docker containers from Step 3 are fully running before executing this)*

```bash
python manage.py migrate

```

**7. Create a superuser for the Admin Panel:**

```bash
python manage.py createsuperuser

```

---

## 🔑 Adding Telegram Accounts (Initial Step)

Before running any crawlers or campaigns, you must add and authenticate your Telegram accounts (Execution Accounts). This is done via a secure Management Command which handles the MTProto handshake and generates session files.

Run the following command and follow the interactive prompts:

```bash
python manage.py login_telegram

```

* **Process:** You will be asked for the phone number, `API_ID`, `API_HASH`, and the OTP code sent to that Telegram account.
* **Result:** The system will generate a `.session` file in the `sessions/` directory and automatically register a `TelegramAccount` instance in the database.

---

## 🏃‍♂️ Running the System

You need two separate terminal windows to run the web server and the background task worker.

**Terminal 1: Start the Django Server**

```bash
python manage.py runserver

```

**Terminal 2: Start the Celery Worker**
Because Telethon makes heavily asynchronous I/O network calls, we use the `gevent` execution pool for maximum performance and concurrency without blocking the worker.

```bash
celery -A config worker -l info -P gevent -c 100

```

---

## 🏗 System Architecture (Core Apps)

The project is divided into three highly decoupled Django apps:

### 1. `telegram_account`

The foundation of the system. It manages the physical Telegram accounts used by the platform.

* Stores `api_id`, `api_hash`, and session paths.
* Tracks daily limits (`daily_messages_sent`).
* Manages restriction states (`is_restricted`, `restricted_until`) if an account hits a `PeerFloodError`.

### 2. `crawler`

Responsible for finding and extracting your target audience.

* **`TelegramSource`:** Represents a target Group or Channel link.
* **`CrawlerTask`:** A background job that connects to a Source, reads message history, and extracts active users.
* **`CrawledUser`:** The extracted leads. Ensures no duplicate users are saved across the entire database.

### 3. `sender`

The campaign execution engine.

* **`MessageTemplate`:** Reusable texts or voice notes. Smartly handles Telegram file caching per account via `JSONField`.
* **`SenderTask`:** The main campaign. You select target sources, rotation accounts, daily limits, and the sequence of messages to send.
* Uses **Connection Pooling** to keep MTProto connections alive during the campaign loop, drastically reducing the risk of bans and TCP drops.

---

## 🎯 Admin Panel Workflow (How to Use)

Once the system is running and you've added accounts via CLI, manage your operations through the Django Admin Panel (`http://127.0.0.1:8000/admin/`).

### Phase 1: Crawling (Lead Generation)

1. Navigate to **Crawler > Telegram Sources**. Add a new target group or channel link.
2. Navigate to **Crawler > Crawler Tasks**. Click "Add".
3. Select an **Execution Account** and your newly created **Target Source**.
4. Set limits (e.g., extract 500 users).
5. **Save.** Celery will automatically pick up the task in the background. You can monitor the progress (Users Crawled) in the admin list view.

### Phase 2: Creating Message Templates

1. Navigate to **Sender > Message Templates**.
2. Create templates for your campaign.
* *Example:* Create a "TEXT" template for an initial greeting.
* *Example:* Create a "VOICE" template by uploading an `.ogg` file. The system will automatically handle the Telegram upload cache in the background for each rotating account.



### Phase 3: Sending the Campaign

1. Navigate to **Sender > Sender Tasks**. Click "Add".
2. **Targeting:** Select the `TelegramSource` you crawled earlier. The system will only message users extracted from these sources who are in the `PENDING` state.
3. **Execution Rotation:** Select multiple `TelegramAccount`s. The system will rotate between them automatically.
4. **Anti-Spam:** Set the daily limit per account (e.g., 25) and the delay between messages (e.g., 60 seconds).
5. **Messages (Inlines):** At the bottom of the page, add your `MessageTemplate`s and define their order (e.g., Order 1: Text Greeting, Order 2: Voice Note).
6. **Save.** Celery will initiate the campaign, establish connection pools, and securely dispatch your sequence to the target users.

---

*Developed with Django, Celery, and Telethon.*