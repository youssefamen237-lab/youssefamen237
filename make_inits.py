import os

current_dir = os.getcwd()
count = 0

print("?? Creating __init__.py files...")

for root, dirs, files in os.walk(current_dir):
   
    dirs[:] = [d for d in dirs if not d.startswith('.')]
    
  
    if root != current_dir:
        init_file = os.path.join(root, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                pass
            print(f"?? Created: {os.path.relpath(init_file, current_dir)}")
            count += 1

print(f"===============")
print(f"? Success! Created {count} __init__.py files.")