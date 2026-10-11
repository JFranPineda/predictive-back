"""One view mounted on two routes: the collection route creates, the item
route deletes.

Mounted plainly, a DELETE on the collection or a POST on the item reached a
method without the argument it needs and answered 500. Narrowing each route
to its method makes the wrong one a 405.
"""

CREATE_ONLY = {"http_method_names": ["post", "options"]}
DELETE_ONLY = {"http_method_names": ["delete", "options"]}
