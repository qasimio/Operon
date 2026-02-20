def ask_user_approval(action: str, payload: dict) -> bool:
    print("\n--- Operon REQUEST ---")
    print("Action:", action)
    print("Payload:", payload)
    print("----------------------")

    while True:
        choice = input("Approve? (y/n): ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
