"""Ground truth and hand-audit data for the container UI-detection experiment.

Ground truth was read off the rendered page (1280x800) and the page's own DOM layout:
every box below is a real, interactable or semantic element of container/site/index.html.

`expect` lists the YOLO class names that would be a semantically acceptable label for
that element. Anything else on a geometrically correct box counts as a mislabel.

VLM verdicts were produced by reading each model's answer and checking the claim against
the element that box actually covers:
    correct - the named element matches the covered element
    partial - right widget, imprecise box or imprecise name
    wrong   - a different element
    None    - the model never addressed that box id
"""

# name, bbox [x1, y1, x2, y2], acceptable detector classes
GROUND_TRUTH = [
    ("Flights tab",         [175,   9,  275,  49], {"button"}),
    ("Hotels tab",          [280,  11,  375,  48], {"button"}),
    ("Car hire tab",        [383,  11,  486,  49], {"button"}),
    ("Packages tab",        [495,  10,  613,  49], {"button"}),
    ("Register button",     [1047, 11, 1150,  48], {"button"}),
    ("Sign in button",      [1163, 12, 1252,  49], {"button"}),
    ("Hero heading",        [21,   88,  645, 181], {"heading"}),
    ("From field",          [34,  292,  249, 345], {"field"}),
    ("To field",            [257, 292,  459, 344], {"field"}),
    ("Depart field",        [467, 291,  670, 344], {"field"}),
    ("Return field",        [682, 290,  883, 345], {"field"}),
    ("Travellers field",    [886, 289, 1090, 345], {"field"}),
    ("Search button",       [1102, 289, 1234, 345], {"button"}),
    ("Round-trip label",    [63,  261,  145, 280], {"text"}),
    ("One-way label",       [182, 261,  250, 280], {"text"}),
    ("Multi-city label",    [291, 261,  360, 279], {"text"}),
    ("Round-trip radio",    [46,  262,   62, 278], {"image", "button"}),
    ("One-way radio",       [160, 261,  181, 280], {"image", "button"}),
    ("Multi-city radio",    [269, 261,  287, 279], {"image", "button"}),
    ("Nearby airports box", [43,  356,   63, 376], {"image", "button"}),
    ("Direct flights box",  [232, 356,  249, 375], {"image", "button"}),
    ("Add hotel box",       [429, 356,  449, 375], {"image", "button"}),
    ("Nearby airports lbl", [68,  356,  210, 374], {"text"}),
    ("Direct flights lbl",  [253, 355,  384, 375], {"text"}),
    ("Add hotel lbl",       [448, 356,  513, 375], {"text"}),
    ("Explore heading",     [29,  425,  262, 454], {"heading"}),
    ("India card",          [29,  469,  319, 601], {"button", "link", "image"}),
    ("Japan card",          [345, 469,  629, 601], {"button", "link", "image"}),
    ("Spain card",          [655, 469,  944, 601], {"button", "link", "image"}),
    ("Italy card",          [969, 469, 1258, 601], {"button", "link", "image"}),
    ("Footer note",         [19,  658,  605, 674], {"text"}),
]

# What each detector box actually covers, plus what the VLM said about it.
# key = detector box id; (true element, A2 claim+verdict, B claim+verdict)
BOX_TRUTH = {
    1:  ("Sign in button",      ("Register Button", "wrong"),        ("Sign in button", "correct")),
    2:  ("Register button",     ("Sign in Button", "wrong"),         ("Register button", "correct")),
    3:  ("Travellers field",    ("Flights Tab", "wrong"),            ("Search button", "wrong")),
    4:  ("Nearby airports lbl", ("Headline Text", "wrong"),          ("Return date field label", "wrong")),
    5:  ("From text",           (None, None),                        ("London origin text", "correct")),
    6:  ("Packages tab",        ("Search Button", "wrong"),          ("Car hire tab", "correct")),
    7:  ("Round-trip label",    (None, None),                        ("One-way radio label", "wrong")),
    8:  ("From field",          (None, None),                        ("origin input group", "correct")),
    9:  ("Hero heading",        ("Section Heading 'Explore'", "wrong"), ("Hero heading", "correct")),
    10: ("Hotels tab",          (None, None),                        ("Flights tab", "correct")),
    11: ("Car hire tab",        (None, None),                        ("Hotels tab", "correct")),
    12: ("Direct flights lbl",  (None, None),                        ("Add a hotel label", "wrong")),
    13: ("Depart field",        ("From Field", "wrong"),             ("Depart field", "correct")),
    14: ("Italy card",          (None, None),                        ("Italy card", "correct")),
    15: ("One-way label",       (None, None),                        ("Return radio label", "wrong")),
    16: ("Direct flights box",  ("Country Card", "wrong"),           ("Direct flights checkbox", "correct")),
    17: ("Flights tab",         (None, None),                        ("Packages tab", "correct")),
    18: ("Return field",        (None, None),                        ("Travellers dropdown", "wrong")),
    19: ("To field",            ("To Field", "correct"),             ("Destination field", "correct")),
    20: ("Add hotel lbl",       (None, None),                        ("Add a hotel toggle", "partial")),
    21: ("Footer note",         (None, None),                        ("Footer note", "correct")),
    22: ("Multi-city label",    (None, None),                        ("Travellers label text", "wrong")),
    23: ("Nearby airports box", ("Country Card", "wrong"),           ("Origin field icon", "wrong")),
    24: ("Return field",        ("Travellers/Cabin Field", "wrong"), ("Travellers field, dup of #18", "wrong")),
    25: ("One-way radio icon",  ("Country Card", "wrong"),           ("Icon next to Return radio", "wrong")),
    26: ("Explore heading",     (None, None),                        ("Explore heading", "correct")),
    27: ("Multi-city icon",     ("Country Card", "wrong"),           ("Icon next to One-way radio", "wrong")),
    28: ("Spain card",          (None, None),                        ("Spain card", "correct")),
}
