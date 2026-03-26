from config import cfg


def send_verification_email(email: str, token: str):
    # TODO: Implement actual email sending
    link = f"{cfg().app_host}/api/auth/verify?token={token}"
    print(f"-------------\nVERIFICATION EMAIL TO {email}:\nLink: {link}\n-------------")
