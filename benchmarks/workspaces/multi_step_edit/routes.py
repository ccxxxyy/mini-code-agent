from models import User
from views import get_user_display

def handle_profile(name, email):
    user = User(name, email)
    return get_user_display(user)
