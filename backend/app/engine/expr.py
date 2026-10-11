"""
Tiny, safe arithmetic expression evaluator used for formula-based base prices
and formula adjustments. Supports +,-,*,/,%,**, unary -, parentheses,
numeric literals and variable names resolved from a provided namespace.

Deliberately NOT Python eval(): the AST walker only allows a closed set of
node types, so a malicious or buggy config expression cannot call functions,
import modules, or access attributes.
"""
from __future__ import annotations

import ast
import operator
from typing import Any, Dict

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}
_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ExpressionError(ValueError):
    pass


def safe_eval(expression: str, variables: Dict[str, Any]) -> float:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise ExpressionError(f"Invalid expression '{expression}': {e}") from e
    return _eval_node(tree.body, variables, expression)


def _eval_node(node: ast.AST, variables: Dict[str, Any], expr: str) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ExpressionError(f"Unsupported literal in '{expr}'")
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExpressionError(f"Unknown variable '{node.id}' in expression '{expr}'")
        value = variables[node.id]
        if value is None:
            raise ExpressionError(f"Variable '{node.id}' is missing from context for '{expr}'")
        return float(value)
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _eval_node(node.left, variables, expr)
        right = _eval_node(node.right, variables, expr)
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_eval_node(node.operand, variables, expr))
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in ("min", "max", "round", "abs"):
            args = [_eval_node(a, variables, expr) for a in node.args]
            return {"min": min, "max": max, "round": round, "abs": abs}[node.func.id](*args)
        raise ExpressionError(f"Function calls are not allowed in '{expr}'")
    raise ExpressionError(f"Unsupported syntax in expression '{expr}'")
