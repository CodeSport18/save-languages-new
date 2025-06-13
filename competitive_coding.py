# https://codeforces.com/problemset/problem/1914/C

# t = int(input())
# outputs = []

# for _ in range(t):
#     n, k = map(int, input().split())
#     a = list(map(int, input().split()))
#     b = list(map(int, input().split()))
    
#     prefix_a = [0] * (n + 1)
#     prefix_b = [0] * (n + 1)
#     for i in range(n):
#         prefix_a[i + 1] = prefix_a[i] + a[i]
#         prefix_b[i + 1] = prefix_b[i] + b[i]
    
#     max_exp = 0
#     for i in range(min(n, k) + 1):
#         exp = prefix_a[i]
#         remaining = k - i
#         if remaining > 0:
#             exp += remaining * b[i-1] if i > 0 else 0
#         max_exp = max(max_exp, exp)
    
#     outputs.append(max_exp)

# for output in outputs:
#     print(output)





# https://codeforces.com/problemset/problem/1624/D

# t = int(input())

# outputs = []

# for _ in range(t):
#     n, k = map(int, input().split())
#     s = input().strip()
    
#     freq = {}
#     for char in s:
#         freq[char] = freq.get(char, 0) + 1
    
#     pairs = 0
#     singles = 0
#     for count in freq.values():
#         pairs += count // 2
#         singles += count % 2
    
#     max_pairs_per_palindrome = pairs // k
#     remaining_pairs = pairs % k
    
#     if remaining_pairs > 0 or singles > 0:
#         outputs.append(2 * max_pairs_per_palindrome + 1)
#     else:
#         outputs.append(2 * max_pairs_per_palindrome)

# for output in outputs:
#     print(output)