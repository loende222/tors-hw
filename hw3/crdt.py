import enum
import threading
import time
import flask
import requests
import os
import random
import logging

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

INDEX_TO_URL = {
    0: 'http://crdt-0:7000',
    1: 'http://crdt-1:7001',
    2: 'http://crdt-2:7002',
}

class CRDT:
    def __init__(self, index):
        self._state = {}
        self._index = index
        self._last_entry_clock = {}

        self.app = flask.Flask("CRDT")
        self.app.logger.disabled = True

        self.app.add_url_rule('/patch', "patch", self.patch, methods=['PATCH'])
        self.app.add_url_rule('/get', "get", self.get, methods=['GET'])
        self.app.add_url_rule('/sync', "sync", self.sync, methods=['POST'])

        threading.Thread(target=self.sync_job).start()

        self.app.run(host='0.0.0.0', port=7000 + self._index, threaded=True)
    
    def merge(self, other_state, other_clock):
        for key, value in other_state.items():
            other_clock_for_key = other_clock[key]
            clock_for_key = [0] * len(INDEX_TO_URL)
            if key in self._last_entry_clock:
                clock_for_key = self._last_entry_clock[key]

            other_greater = False
            self_greater = False
 
            for i in range(len(INDEX_TO_URL)):
                if other_clock_for_key[i] > clock_for_key[i]:
                    other_greater = True
                if other_clock_for_key[i] < clock_for_key[i]:
                    self_greater = True
            
            if other_greater and not self_greater:
                self._state[key] = value
                self._last_entry_clock[key] = other_clock[key]


    def patch(self):
        request = flask.request.get_json()
        patch = request.get("patch")

        print(patch)
        for key, value in patch.items():
            self._state[key] = value
            if key not in self._last_entry_clock:
                self._last_entry_clock[key] = [0] * len(INDEX_TO_URL)
            self._last_entry_clock[key][self._index] += 1

            print(self._last_entry_clock[key])
        
            for index, url in INDEX_TO_URL.items():
                if index == self._index: continue
                try:
                    response = requests.post(f'{INDEX_TO_URL[index]}/sync', json={'state': self._state, 'clock': self._last_entry_clock}, timeout=1)
                except:
                    pass
        return flask.jsonify("OK"), 200


    def get(self):
        return flask.jsonify({"state": self._state, "clock": self._last_entry_clock}), 200


    def sync(self):
        request = flask.request.get_json()
        other_state = request.get("state")
        other_clock = request.get("clock")

        self.merge(other_state, other_clock)
        return flask.jsonify("OK"), 200


    def sync_job(self):
        while True:
            for index, url in INDEX_TO_URL.items():
                if index == self._index: continue
                try:
                    response = requests.get(f'{INDEX_TO_URL[index]}/get', timeout=1)
                    response_json = response.json()
                    self.merge(response_json["state"], response_json["clock"])
                except:
                    print('Error ocurred while sync job')
                    pass
            time.sleep(5)


crdt = CRDT(int(os.environ['INDEX']))
