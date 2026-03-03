class JobActionNotFound(Exception):
    def __init__(self, action: str):
        super().__init__(f"Job action not found: {action!r}")
        self.action = action


class A:
    def ciao(self, payload):
        return f"ciao {payload}"

    def best(self, payload):
        return f"best {payload}"

    def run(self, action: str, payload):
        fn = getattr(self, action, None)  # get method named like action
        if fn is None or not callable(fn):
            raise JobActionNotFound(action)
        return fn(payload)


test = {"action": "ciao", "payload": {"x": 1}}
a = A()
result = a.run(test["action"], test["payload"])
print(result)
