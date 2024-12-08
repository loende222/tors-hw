
class Operation:
    def __init__(self, key, value, index, commited):
        self._key = key
        self._value = value
        self._index = index
        self._commited = commited


class WrongOperation(Exception):
    def __init__(self, message):
        self._message = message


class NeedSyncException(Exception):
    def __init__(self, last_log):
        self._last_log = last_log


class Storage:
    def __init__(self):
        self._log = []


    def get_first_not_commited(self):
        ind = 0
        for log in self._log:
            if log._commited:
                ind += 1
            else:
                break
        return ind


    def update_log(self, operations):
        for operation in operations:
            if operation._index < self.get_first_not_commited():
                print('Operation is already commited')
            elif operation._index == self.get_first_not_commited():
                print('Updating the operation')
                if operation._index < len(self._log):
                    print("Here commiting")
                    self._log[operation._index] = operation
                else:
                    self._log.append(operation)
            else:
                print('Need synchronization')
                raise NeedSyncException(self.get_first_not_commited())


    def create(self, key, value, index):
        if (self.read(key) is not None):
            raise WrongOperation("[CREATE] Key already exists")
        operation = Operation(key, value, index, False)
        self._log.append(operation)
        return operation


    def read(self, key):
        value = None
        for operation in self._log:
            if operation._key == key and operation._commited:
                value = operation._value
        return value


    def update(self, key, value, index):
        if (self.read(key) is None):
            raise WrongOperation("[UPDATE] Key does not exist")
        operation = Operation(key, value, index, False)
        self._log.append(operation)
        return operation


    def delete(self, key, index):
        if (self.read(key) is None):
            raise WrongOperation("[DELETE] Key does not exist")
        operation = Operation(key, None, index, False)
        self._log.append(operation)
        return operation
