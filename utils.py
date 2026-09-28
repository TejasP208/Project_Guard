import random
import string

def generate_team_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))