import threading

# Initialize bot_ready event
bot_ready = threading.Event()

class BotState:
    def __init__(self):
        self.ready = False

    def set_ready(self):
        self.ready = True

    def is_ready(self):
        return self.ready

# Instantiate the state as a singleton
bot_state = BotState()
