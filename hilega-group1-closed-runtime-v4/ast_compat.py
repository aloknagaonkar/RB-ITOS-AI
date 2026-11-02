"""Preserve the reviewed Python 3.12 AST dump format across interpreter versions."""
import ast
from inspect import signature


def reviewed_dump(node,*,dumper=ast.dump):
    options={'include_attributes':False}
    if 'show_empty' in signature(dumper).parameters:
        options['show_empty']=True
    return dumper(node,**options)
