# 🚀 Setup Instructions
## 1. 📥 Install Requirements

First, install the required Python packages:

<pre> pip install -r requirements.txt </pre>

## 2. 🔐 Generate a Gmail App Password

To send email alerts, you'll need to generate a 16-character App Password from your Gmail account (if using Gmail):

Visit: [Generate App Password](https://myaccount.google.com/apppasswords?pli=1&rapt=AEjHL4M2MxC18KZPcWAeBVtDM3aaWPQkbqUT-SlWQk02W451xsKataD6w93d3Y7Hba9lPhRgMnjdFxUv5bxmCHQemru_U8ocxMwJrCni_7BCu6qojwnCekg)

Copy the 16-character password provided.

## 3. ⚙️ Create and Configure .env File

Create a .env file in the root of the project to securely store your credentials:

<pre> touch .env </pre>

Add the following lines, replacing the placeholders with your actual values:

<pre>
RESY_EMAIL=your_resy_login_email

RESY_PASSWORD=your_resy_password

SENDER_EMAIL=your_gmail_email

SENDER_PASSWORD=your_16_character_app_password

RECEIVER_EMAIL=recipient_email_for_alerts
</pre>

🔒 Do not commit your .env file to Git. Add it to your .gitignore.
