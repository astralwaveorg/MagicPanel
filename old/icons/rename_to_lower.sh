#!/bin/bash
# 遍历当前目录下的所有文件
for file in *; do
    # 检查是否是文件（而不是目录）
    if [ -f "$file" ]; then
        # 将文件名转换为小写
        lowercase=$(echo "$file" | tr '[:upper:]' '[:lower:]')
        # 检查目标文件是否已经存在
        if [ "$file" != "$lowercase" ]; then
            # 如果目标文件存在，添加后缀
            new_file="$lowercase"
            count=1
            
            while [ -e "$new_file" ]; do
                new_file="${lowercase%.*}_$count.${lowercase##*.}" # 在文件名中添加后缀
                ((count++))
            done
            
            # 重命名文件
            mv "$file" "$new_file"
            echo "重命名: $file -> $new_file"
        fi
    fi
done

