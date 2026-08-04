from models import User

def get_user_display(user: User) -> str:
    return f"{user.name} <{user.email}>"
