ROOM_LABELS = [
    "a bedroom with a bed",
    "a living room with a sofa",
    "a kitchen with appliances",
    "a bathroom with a toilet or shower",
    "a dining room with a dining table",
    "an exterior view of a house or building",
    "another type of room or space",
]

ROOM_TYPES = [
    "bedroom",
    "living_room",
    "kitchen",
    "bathroom",
    "dining_room",
    "exterior",
    "other",
]

CONDITION_PROMPTS = [
    "a well-maintained, clean, renovated room in excellent condition",
    "an average condition room, moderately maintained",
    "a rundown, neglected, poor condition room",
]

# Weight per prompt: well-maintained=1.0, average=0.5, rundown=0.0
CONDITION_WEIGHTS = [1.0, 0.5, 0.0]
