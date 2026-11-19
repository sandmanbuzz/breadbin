/* The docs/design/pvm.md benchmark in C, for tools/cc.py and cc65 (tools/pvm_bench.py). bench.pla is the same program in PLASMA. */
char flags[200];
int a[10];
int sieve() {
  int i = 0; int j = 0; int n = 0;
  for (i = 2; i <= 199; i = i + 1) flags[i] = 1;
  for (i = 2; i <= 199; i = i + 1) {
    if (flags[i]) {
      n = n + 1;
      j = i + i;
      while (j < 200) { flags[j] = 0; j = j + i; }
    }
  }
  return n;
}
int gcd(int x, int y) {
  while (x != y) { if (x > y) x = x - y; else y = y - x; }
  return x;
}
int sum() {
  int i = 0; int s = 0;
  for (i = 0; i <= 9; i = i + 1) a[i] = i * 3;
  for (i = 0; i <= 9; i = i + 1) s = s + a[i];
  return s;
}
int main() {
  int t = sieve(); int k = 0;
  for (k = 1; k <= 20; k = k + 1) t = t + gcd(k * 6, 84);
  return t + sum();
}
