import threading

# Initialize bot_ready event
bot_ready = threading.Event()

class BotState:
    def __init__(self):
        self.ready = False
        self.managed_message_ids = set()

    def set_ready(self):
        self.ready = True

    def is_ready(self):
        return self.ready

    def add_managed_message_id(self, message_id):
        self.managed_message_ids.add(message_id)

    def get_managed_message_ids(self):
        return self.managed_message_ids

# Instantiate the state as a singleton
bot_state = BotState()