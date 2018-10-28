import requests

class Remote():
    def authenticate(self):
        return NotImplemented

    def submit_racer_update(self):
        return NotImplemented

class SimulatedRemote(Remote):
    def authenticate(self):
        pass

class OnTheDayRemote(Remote):
    pass
