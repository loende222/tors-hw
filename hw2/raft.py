import enum
import threading
import time
import flask
import requests
import os
import random
import logging

from time import sleep
from storage import *


log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

class State(enum.Enum):
    follower = 0
    leader = 1
    candidate = 2


HEARTBEAT_SEC = 1
MAX_ALLOWED_HEARTBEAT_TIMEOUT = random.uniform(2, 5)
storage = Storage()

PEERS = [1, 2, 3, 4]

INDEX_TO_URL = {
    1: 'http://raft-1:5001',
    2: 'http://raft-2:5002',
    3: 'http://raft-3:5003',
    4: 'http://raft-4:5004'
}


class Raft:
    def __init__(self):
        self._id = int(os.environ['INDEX'])
        self._leader_id = None
        self._last_heartbeat = time.time()
        self._term = 0
        self._state = State.follower.name
        self._votes_list = {}
        self._shutdown = False

        self.app = flask.Flask("RAFT")
        self.app.logger.disabled = True
        self.app.add_url_rule('/create', "create", self.create, methods=['POST'])
        self.app.add_url_rule('/read', "read", self.read, methods=['GET'])
        self.app.add_url_rule('/update', "update", self.update, methods=['PATCH'])
        self.app.add_url_rule('/delete', "delete", self.delete, methods=['DELETE'])

        self.app.add_url_rule('/append_entries', "append_entries", self.append_entries, methods=['POST'])
        self.app.add_url_rule('/request_votes', "request_votes", self.request_votes, methods=['POST'])
        self.app.add_url_rule('/request_log_entries', "request_log_entries", self.request_log_entries, methods=['POST'])

        self.app.add_url_rule('/shutdown', "shutdown", self.shutdown, methods=['POST'])
        self.app.add_url_rule('/restart', "restart", self.restart, methods=['POST'])


        threading.Thread(target=self.send_heartbeat).start()
        threading.Thread(target=self.election_manager).start()

        self.app.run(host='0.0.0.0', port=5000 + self._id, threaded=True)


    def send_heartbeat(self):
        while True:
            if self._shutdown:
                continue
            if self._state == State.leader.name:
                for peer in PEERS:
                    if peer == self._id: continue
                    requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : []})
                self._last_heartbeat = time.time()
            sleep(HEARTBEAT_SEC)


    def election_manager(self):
        while True:
            if self._shutdown:
                continue
            if self._state != State.leader.name and time.time() - self._last_heartbeat > MAX_ALLOWED_HEARTBEAT_TIMEOUT:
                self._state = State.candidate.name
                votes = 0
                self._term += 1
                print("# CANDIDATE # Starting election")
                for peer in PEERS:
                    try:
                        response = requests.post(f'{INDEX_TO_URL[peer]}/request_votes', json={'term' : self._term, 'candidate' : self._id, 'log_len' : storage.get_first_not_commited()})
                        if response.json().get('granted'):
                            print(f"# CANDIDATE # {peer} voted for me")
                            votes += 1
                    except:
                        pass
                if votes >= len(PEERS) // 2 + 1:
                    print("# CANDIDATE -> LEADER #")
                    self._state = State.leader.name
                    self._leader_id = self._id
                else:
                    print("# CANDIDATE -> FOLLOWER")
                    self._state = State.follower.name
            sleep(HEARTBEAT_SEC)


# ---------------- DATABASE HANDLERS ----------------
    def create(self):
        if self._shutdown:
            return '', 500
        print("/create")
        request = flask.request.get_json()
        key, value = request.get("key"), request.get("value")
        if self._state == State.leader.name:
            try:
                operation = storage.create(key, value, storage.get_first_not_commited())
            except WrongOperation as e:
                print(e._message)
                return flask.jsonify({'status': e._message}), 500

            # Sending new operation to peers
            delivered = 1 # Saved to our log only
            for peer in PEERS:
                if peer == self._id:
                    continue
                response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                if response.status_code == 200: delivered += 1

            if delivered >= len(PEERS) // 2 + 1:
                print("Commited successfully")
                operation._commited = True
                storage._log[operation._index]._commited = True
                for peer in PEERS:
                    if peer == self._id:
                        continue
                    print(vars(operation))
                    response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                return flask.jsonify({'status': 'OK'}), 201
            else:
                print("Consensus on commit not reached")
                # Followers will face incorrect log issue and request for clarification
                self._log.pop(-1)
                return 'Consensus not reached', 500
        else:
            print(f"Redirecting request to leader: {self._leader_id}")
            response = requests.post(f'{INDEX_TO_URL[self._leader_id]}/create', json=request)
            return flask.jsonify(response.json()), response.status_code


    def read(self):
        if self._shutdown:
            return '', 500
        print('/read')
        request = flask.request.get_json()
        key = request.get("key")
        value = storage.read(key)

        # if self._state == State.leader.name:
            # TODO redirect to follower

        if value is None:
            return flask.jsonify({'status': 'Not found'}), 404
        return flask.jsonify({'value': value}), 200


    def delete(self):
        if self._shutdown:
            return '', 500
        request = flask.request.get_json()
        key = request.get("key")

        if self._state == State.leader.name:
            try:
                operation = storage.delete(key, storage.get_first_not_commited())
            except WrongOperation as e:
                print(e._message)
                return flask.jsonify({'status': e._message}), 500
            
            # Sending new operation to peers
            delivered = 1 # Saved to our log only
            for peer in PEERS:
                if peer == self._id:
                    continue
                response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                if response.status_code == 200: delivered += 1

            if delivered >= len(PEERS) // 2 + 1:
                print("Commited successfully")
                operation._commited = True
                storage._log[operation._index]._commited = True
                for peer in PEERS:
                    if peer == self._id:
                        continue
                    response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                return flask.jsonify({'status': 'OK'}), 200
            else:
                print("Consensus on commit not reached")
                # Followers will face incorrect log issue and request for clarification
                self._log.pop(-1)
                return 'Consensus not reached', 500
        else:
            print(f"Redirecting request to leader: {self._leader_id}")
            response = requests.delete(f'{INDEX_TO_URL[self._leader_id]}/delete', json=request)
            return flask.jsonify(response.json()), response.status_code


    def update(self):
        if self._shutdown:
            return '', 500
        request = flask.request.get_json()
        key, value = request.get("key"), request.get("value")

        if self._state == State.leader.name:
            try:
                operation = storage.update(key, value, storage.get_first_not_commited())
            except WrongOperation as e:
                print(e._message)
                return flask.jsonify({'status': e._message}), 500

            # Sending new operation to peers
            delivered = 1 # Saved to our log only
            for peer in PEERS:
                if peer == self._id:
                    continue
                response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                if response.status_code == 200: delivered += 1

            # Sending new operation to peers
            delivered = 1 # Saved to our log only
            for peer in PEERS:
                if peer == self._id:
                    continue
                response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                if response.status_code == 200: delivered += 1

            if delivered >= len(PEERS) // 2 + 1:
                print("Commited successfully")
                operation._commited = True
                storage._log[operation._index]._commited = True
                for peer in PEERS:
                    if peer == self._id:
                        continue
                    response = requests.post(f'{INDEX_TO_URL[peer]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : [vars(operation)]})
                return flask.jsonify({'status': 'OK'}), 200
            else:
                print("Consensus on commit not reached")
                # Followers will face incorrect log issue and request for clarification
                self._log.pop(-1)
                return 'Consensus not reached', 500
        else:
            print(f"Redirecting request to leader: {self._leader_id}")
            response = requests.patch(f'{INDEX_TO_URL[self._leader_id]}/update', json=request)
            return flask.jsonify(response.json()), response.status_code


# ---------------- RAFT HANDLERS ----------------
    def append_entries(self):

        if self._shutdown:
            return '', 500
        request = flask.request.get_json()

        term = request.get('term')
        leader = request.get('leader')
        modifications = request.get('modifications')

        if term < self._term:
            print(f"Term {term} from {leader} is lower than my term {self._term}")
            return flask.jsonify({'status': 'Bad Request'}), 400
        
        self._last_heartbeat = time.time()

        if (leader != self._leader_id):
            print(f'Considering {leader} is leader in term {term}')
        self._term = term
        self._leader_id = leader
        self._state = State.follower.name

        operations = []
        for op in modifications:
            obj = Operation(
                op.get('_key'),
                op.get('_value'),
                op.get('_index'),
                op.get('_commited')
            )
            operations.append(obj)

        if len(operations) > 0:
            try:
                storage.update_log(operations)
            except NeedSyncException as e:
                print('Sending /request_log_entries')
                response = requests.post(f'{INDEX_TO_URL[self._leader_id]}/request_log_entries', json={'id' : self._id, 'log_start' : storage.get_first_not_commited()})

        return flask.jsonify({'status': 'OK'}), 200


    def request_log_entries(self):
        print('Received /request_log_entries')
        # request to catch up log entries can be send only to leader

        if self._id != self._leader_id:
            return 'Cannot serve this request', 500
        
        request = flask.request.get_json()
        id = request.get('id')
        log_start = request.get('log_start')
        operations_since = storage._log[log_start:]
        modifications = []
        for op in operations_since:
            modifications.append(vars(op))

        requests.post(f'{INDEX_TO_URL[id]}/append_entries', json={'term' : self._term, 'leader' : self._id, 'modifications' : modifications})
        return 'OK', 200


    def request_votes(self):
        if self._shutdown:
            return '', 500

        request = flask.request.get_json()
        term = request.get('term')
        candidate = request.get('candidate')
        log_len = request.get('log_len')

        if term < self._term:
            print(f"Term {term} from {candidate} is lower than my term {self._term}")
            return flask.jsonify({'granted': False}), 400
        
        self._last_heartbeat = time.time()
        self._term = term
    
        if term in self._votes_list or log_len < storage.get_first_not_commited():
            return flask.jsonify({'granted': False}), 200

        self._votes_list[term] = candidate
        return flask.jsonify({'granted': True}), 200


# ---------------- TESTING HANDLERS ----------------
    def shutdown(self):
        print(f'# {self._id} # Shut down')
        self._shutdown = True
        return '', 200

    def restart(self):
        print(f'# {self._id} # Restart')
        self._shutdown = False
        return '', 200


raft = Raft()

