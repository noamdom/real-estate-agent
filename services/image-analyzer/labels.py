OPEN_LABELS = [
    "a bedroom with a bed and pillows",
    "a living room or lounge with sofa and furniture",
    "a kitchen with appliances, sink or cabinets",
    "a bathroom with toilet, shower or bathtub",
    "a dining room with table and chairs",
    "an exterior view of a house, apartment building or residential block",
    "an outdoor garden, balcony, terrace or yard of a property",
    "a parking space, garage or driveway",
    "an office, commercial workspace or meeting room",
    "a hallway, corridor, staircase or entrance of a building",
    "a cat, dog, bird or other animal",
    "a person, people or portrait",
    "food, beverages or a meal",
    "a car, motorcycle, truck or other vehicle",
    "a natural landscape, forest, field or park without buildings",
    "a document, screen, phone or piece of paper",
    "an unidentifiable or random object",
]

CONDITION_PROMPTS = [
    "a well-maintained, clean, renovated room in excellent condition",
    "an average condition room, moderately maintained",
    "a rundown, neglected, poor condition room",
]

# Weight per prompt: well-maintained=1.0, average=0.5, rundown=0.0
CONDITION_WEIGHTS = [1.0, 0.5, 0.0]
