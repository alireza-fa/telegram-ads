import os

from django.core.management.base import BaseCommand
from telegram_account.models import TelegramAccount
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError


class Command(BaseCommand):
    help = 'Login to Telegram account and create session file'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=== Telegram Account Login System ==="))

        # 1. Get phone number
        phone_number = input("Enter phone number (e.g., +989123456789): ").strip()
        if not phone_number.startswith('+'):
            self.stdout.write(self.style.ERROR("Error: Phone number must start with +."))
            return

        # 2. Check database for account
        account, created = TelegramAccount.objects.get_or_create(
            phone_number=phone_number,
            defaults={'api_id': 0, 'api_hash': ''}
        )

        # 3. Get API ID and API Hash (if new account or fields are empty)
        if created or not account.api_id or not account.api_hash:
            try:
                api_id = int(input("Enter API ID: ").strip())
                api_hash = input("Enter API Hash: ").strip()
                account.api_id = api_id
                account.api_hash = api_hash
                account.save()
            except ValueError:
                self.stdout.write(self.style.ERROR("Error: API ID must be an integer."))
                return
        else:
            self.stdout.write(self.style.WARNING(f"Account {phone_number} found in database."))

        # Ensure sessions directory exists
        os.makedirs("sessions", exist_ok=True)

        # 4. Connect to Telegram and request code
        self.stdout.write("Connecting to Telegram servers...")
        client = TelegramClient(account.session_path, account.api_id, account.api_hash)

        try:
            client.connect()

            # Check if session is already authorized
            if not client.is_user_authorized():
                self.stdout.write(self.style.WARNING("Session not authorized. Sending code..."))
                client.send_code_request(phone_number)

                code = input("Enter the login code sent via SMS/Telegram: ").strip()

                try:
                    # Attempt to sign in with code
                    client.sign_in(phone_number, code)
                except SessionPasswordNeededError:
                    # Handle Two-Step Verification (2FA)
                    password = input("Account has Two-Step Verification. Enter password: ").strip()
                    client.sign_in(password=password)
                except PhoneCodeInvalidError:
                    self.stdout.write(self.style.ERROR("Error: Invalid code entered."))
                    return

            # 5. Final confirmation and database update
            me = client.get_me()
            account.is_active = True
            account.save()

            self.stdout.write(self.style.SUCCESS(
                f"✅ Login successful! \n"
                f"👤 Account Name: {me.first_name} \n"
                f"📁 Session saved at {account.session_path}.session"
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Unexpected error occurred: {str(e)}"))

        finally:
            client.disconnect()
