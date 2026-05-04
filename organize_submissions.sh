#\!/bin/bash
DEST="$HOME/Documents/Projects/course-grader/submissions"
mkdir -p "$DEST/הגשה_1" "$DEST/הגשה_2" "$DEST/הגשה_סופית"
cd "$HOME/Downloads"
for folder in הגשה_1 הגשה_2 הגשה_סופית; do
    count=0
    for f in "${folder}_"*; do
        [ -f "$f" ] && mv "$f" "$DEST/$folder/" && ((count++))
    done
    echo "Moved $count files → $folder"
done
echo "Done. Files in: $DEST"
