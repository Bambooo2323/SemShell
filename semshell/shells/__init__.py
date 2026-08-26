"""Equal user-space Operator ProcessPrograms."""

from semshell.shells.base import OperatorTask
from semshell.shells.human import HumanShell
from semshell.shells.llm import LLMShell
from semshell.shells.rule import Rule, RuleShell

__all__ = ["HumanShell", "LLMShell", "OperatorTask", "Rule", "RuleShell"]
