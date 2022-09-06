"""
Shell interface
"""

import asyncio as aio
import cmd
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Coroutine
from sys import stdin, stdout
from typing import Any, TextIO, TypeVar


class Shell(cmd.Cmd):
    def __init__(self, istream: TextIO = stdin, ostream: TextIO = stdout):
        """
        Initialize the base class with IO streams
        `use_rawinput` will be set to `True` if and only if `istream` is `sys.stdin`.
        """

        self.__istream = istream
        self.__ostream = ostream

        self.__use_rawinput = istream is stdin

        super().__init__(stdin=istream, stdout=ostream)

    @property
    def use_rawinput(self):
        """
        Shadows the `use_rawinput` class attribute to make it instance-bound.
        """
        return self.__use_rawinput

    def default(self, _):
        """
        Exit the shell if needed
        It overrides the base class method of the same name. It allows to leave the shell whatever the input line might be.
        """
        return not self.__continue

    def do_EOF(self, _) -> bool:
        """
        Exit the shell
        It is invoked when an end-of-file is received
        """
        return True

    async def run(self) -> None:
        """
        Start a shell session asynchronously
        """
        self.__loop = aio.get_event_loop()
        self.__continue = True
        await aio.to_thread(self.cmdloop)

    def create_task(self, coro: Coroutine) -> bool:
        """
        Schedule a coroutine to be carried out
        This method is thread-safe. This function is meant to schedule commands to be done. Thus, if the shell is stopping, this method will have no effect.
        """
        if not self.__continue:
            return True
        self.__loop.call_soon_threadsafe(self.__create_task, coro)
        return False

    def __create_task(self, coro: Coroutine):
        """
        Schedule a coroutine to be carried out
        This method is not thread-safe and should only be called through `create_task`.
        """
        task = self.__loop.create_task(coro)
        task.add_done_callback(self.__finalize_task)

    def __finalize_task(self, task: aio.Task):
        """
        Handle a command finalization
        When a task associated to a command is done, this function is invoked to handle potential exception.
        """
        try:
            e = task.exception()
            if e is not None:
                raise e
        except ShellError as e:
            self.__ostream.write(str(e) + "\n")
        except Exception as e:
            self.__continue = False
            self.__ostream.write(f"An unrecoverable error has occured : {e}\n")
            self.__ostream.write("Press ENTER to quit.\n")


ShellType = TypeVar("ShellType", bound=Shell)


class ShellError(Exception):
    """
    Used to signal a recoverable error to the shell
    When caught, the shell is not interrupted contrary to the other kind of exception.
    """

    def __init__(self, message: str = None):
        super().__init__(message)


def command(f: Callable[[ShellType, str], Any]) -> Callable[[ShellType, str], bool]:
    """
    Make a command compatible with the underlying `cmd.Cmd` class
    It should only be used on methods of a class derived from `Shell` whose identifiers begin with 'do_'.
    """
    return lambda self, line: self.create_task(f(self, line))


def argument(*args, **kwargs) -> Callable[[Callable], Callable]:
    """
    Provide an argument specification
    This decorator behaves like the `ArgumentParser.add_argument` method. However, the result from the call of `ArgumentParser.parse_args` is unpacked to the command.
    """

    def impl(f):
        if type(f) is not _Wrapper:
            f = _Wrapper(f)

        f.parser.add_argument(*args, **kwargs)
        return f

    return impl


class _Wrapper:
    def __init__(self, f: Callable):
        """
        Hold a callable which will received the CLI arguments
        """
        self.__f = f
        self.parser = _Parser(prog=f.__name__)

    async def __call__(self, shell: Shell, line: str) -> None:
        """
        Forward the accumulated CLI argument to the held callable
        """
        await self.__f(shell, **vars(self.parser.parse(line)))


class _Parser(ArgumentParser):
    def __init__(self, *args, **kwargs):
        """
        Initialize the underlying parser
        """
        super().__init__(
            *args,
            **kwargs,
        )

    def parse(self, line: str) -> Namespace:
        """
        Parse the argument from a command line
        Instead of exiting the program, this method will raise a `ShellError()` if the parsing fails.
        """
        try:
            return self.parse_args(line.split())
        except SystemExit:
            raise ShellError()
