"""Helpers shared by the page modules.

Strictly layered so no import cycle is possible:
constants -> io -> data -> projects -> models -> widgets -> state.
A module may import only from the levels below it.
"""
