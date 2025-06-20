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








# https://usaco.org/index.php?page=viewproblem2&cpid=1088

# n = int(input())

# grid_by_rows = [list(map(int, input().split())) for _ in range(n)]

# grid_by_cols = zip(*grid_by_rows)

# rows_alternate = 0
# columns_alternate = 0

# for i in range(n):

# 	ith_row = grid_by_rows[i]

# 	rows_alternate += max(sum(ith_row[::2]), sum(ith_row[1::2]))

# 	ith_col = next(grid_by_cols)
# 	columns_alternate += max(sum(ith_col[::2]), sum(ith_col[1::2]))

# print(max(rows_alternate, columns_alternate))








# https://usaco.org/index.php?page=viewproblem2&cpid=1491

grid_size, updates = (int(x) for x in input().split())
original_grid = [[x == '#' for x in input()] for asdf in range(grid_size)]

def getanswer(original_grid):
  
  best = grid_size*grid_size
  
  for grid in range(2 ** ((grid_size**2)//4)):
    wrongcount = 0

    for i in range(grid_size//2+1):
      for j in range(grid_size//2+1):

        truei = min(i, grid_size-1-i)
        truej = min(j, grid_size-1-j)

        if original_grid[i][j] != ((grid & (2 ** (truei * (grid_size // 2) + truej))) != 0):
          wrongcount += 1

    best = min(best, wrongcount)

  return best

print(getanswer(original_grid))

for asdf in range(updates):
  a, b = (int(x)-1 for x in input().split())
  original_grid[a][b] = not original_grid[a][b]
  print(getanswer(original_grid))