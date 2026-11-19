"""Bounded, transport-independent prompt assembly and one-shot selection."""


class Prompt:
    def __init__(self):
        self.active = None

    def clear(self):
        self.active = None

    def begin(self, message, state):
        expected = "question" if message["kind"] == "form" else "permission"
        if state != expected:
            raise ValueError("Prompt does not match state")
        self.active = {"kind": message["kind"], "token": message["token"],
                       "text": message["text"], "parts": [message["text"]] + [None] * (message["parts"] - 1),
                       "options": [None] * message["count"],
                       "selected": 0, "sent": False,
                       "title_at": None, "option_at": None}

    def part(self, message):
        prompt = self.active
        if prompt is None or message["token"] != prompt["token"] or not 1 <= message["index"] < len(prompt["parts"]):
            raise ValueError("No matching prompt part")
        prompt["parts"][message["index"]] = message["text"]
        if all(part is not None for part in prompt["parts"]):
            prompt["text"] = "".join(prompt["parts"])

    def option(self, message):
        prompt = self.active
        if prompt is None or message["token"] != prompt["token"]:
            raise ValueError("No matching prompt")
        if message["index"] >= len(prompt["options"]):
            raise ValueError("Option outside prompt")
        prompt["options"][message["index"]] = message["text"]

    def ready(self):
        if (self.active is not None
                and all(option is not None for option in self.active["options"])
                and all(part is not None for part in self.active["parts"])):
            return self.active
        return None

    def move(self, step):
        prompt = self.ready()
        if prompt is not None and not prompt["sent"]:
            prompt["selected"] = (prompt["selected"] + step) % len(prompt["options"])
            prompt["option_at"] = None

    def choose(self):
        prompt = self.ready()
        if prompt is None or prompt["sent"]:
            return None
        prompt["sent"] = True
        return {"event": "choice", "kind": prompt["kind"],
                "token": prompt["token"], "index": prompt["selected"]}
