import asyncio


def flag_iscoroutinefunction(func):
    func._iscoroutine = asyncio.iscoroutinefunction(func)