import asyncio

from zochat.repl import ReplController


class FakeChat:
    def __init__(self):
        self.calls = 0

    async def __call__(self, question, session):
        self.calls += 1
        class R:
            pass
        r = R()
        r.answer = f"reply to {question}"
        r.session = session
        session.message_history.append(question)
        return r


def test_repl_reset_and_history():
    async def main():
        fc = FakeChat()
        ctrl = ReplController(chat_fn=fc, persist=False)
        await ctrl.handle("hello")
        assert fc.calls == 1
        assert ctrl.last_reply == "reply to hello"
        await ctrl.handle("/history")
        await ctrl.handle("/reset")
        assert ctrl.session.message_history == []
        await ctrl.handle("/session")
        await ctrl.handle("/last")
    asyncio.run(main())


def test_repl_quit():
    async def main():
        fc = FakeChat()
        ctrl = ReplController(chat_fn=fc, persist=False)
        assert await ctrl.handle("/quit") is False
    asyncio.run(main())
