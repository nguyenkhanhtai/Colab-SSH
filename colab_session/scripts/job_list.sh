for f in /root/.colab-jobs/*.json; do
    [ -e "$f" ] || continue
    cat "$f"
    echo "---SEPARATOR---"
done

