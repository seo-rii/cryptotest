package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math/big"
	"os"
	"strconv"
	"strings"
)

const (
	pBits          = 1024
	productBits    = 2 * pBits
	defaultT       = 848
	defaultLimbBit = 16
)

type FixedRange struct {
	Start int      `json:"start"`
	Width int      `json:"width"`
	Value *BigUInt `json:"value"`
}

type BigUInt struct {
	V big.Int
}

func (b *BigUInt) UnmarshalJSON(data []byte) error {
	text := strings.TrimSpace(string(data))
	if text == "null" {
		return nil
	}
	if len(text) >= 2 && text[0] == '"' {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		text = s
	}
	text = strings.ReplaceAll(text, "_", "")
	text = strings.ReplaceAll(text, " ", "")
	if text == "" {
		return fmt.Errorf("empty integer")
	}
	base := 10
	if strings.HasPrefix(text, "0x") || strings.HasPrefix(text, "0X") {
		base = 16
		text = text[2:]
	}
	if _, ok := b.V.SetString(text, base); !ok {
		return fmt.Errorf("invalid integer %q", text)
	}
	if b.V.Sign() < 0 {
		return fmt.Errorf("negative integer %q", text)
	}
	return nil
}

func (b BigUInt) String() string {
	return "0x" + b.V.Text(16)
}

type Input struct {
	T                    int          `json:"T"`
	LimbBits             int          `json:"limb_bits"`
	TailLimbs            int          `json:"tail_limbs"`
	ArithmeticBits       int          `json:"arithmetic_bits"`
	SkipKnownPrefixLimbs int          `json:"skip_known_prefix_limbs"`
	SkipKnownPrefixBits  int          `json:"skip_known_prefix_bits"`
	TailWindowStart      int          `json:"tail_window_start"`
	TailWindowBits       int          `json:"tail_window_bits"`
	TailWindowCarryBits  int          `json:"tail_window_carry_bits"`
	ExactTailCarryLimbs  int          `json:"exact_tail_carry_limbs"`
	ExactCarryBits       int          `json:"exact_carry_bits"`
	LowliftQBits         int          `json:"lowlift_q_bits"`
	QIntervalBound       bool         `json:"q_interval_bound"`
	OddResiduePrimes     []int        `json:"odd_residue_primes"`
	N                    BigUInt      `json:"n"`
	KnownP               BigUInt      `json:"known_p"`
	MaskP                BigUInt      `json:"mask_p"`
	BranchLow            int          `json:"branch_low"`
	BranchHigh           int          `json:"branch_high"`
	FixedP               []FixedRange `json:"fixed_p_ranges"`
	FixedQ               []FixedRange `json:"fixed_q_ranges"`
	DecisionP            []BitRange   `json:"decision_p_ranges"`
	DecisionQ            []BitRange   `json:"decision_q_ranges"`
	PlanArgv             []string     `json:"argv"`
	AssumptionsAs        string       `json:"assumptions_as"`
	NoComments           bool         `json:"no_comments"`
}

type BitRange struct {
	Start int `json:"start"`
	Width int `json:"width"`
}

type LimbRef struct {
	Name       string
	Index      int
	KnownMask  uint16
	KnownValue uint16
	BitVars    [defaultLimbBit]int
}

type ProductTerm struct {
	P      LimbRef
	Q      LimbRef
	Coeff  uint64
	Source string
}

type Column struct {
	Index      int
	TargetLimb uint16
	Terms      []ProductTerm
	Const      *big.Int
	CarryIn    int
	CarryOut   int
	Tail       bool
}

type TailModel struct {
	Input               Input
	LowerLimbCount      int
	TotalColumns        int
	PLimbs              []LimbRef
	QLimbs              []LimbRef
	PHigh               big.Int
	QHigh               big.Int
	QPrefix             big.Int
	QPrefixBits         int
	QPrefixStart        int
	QLowMin             big.Int
	QLowMax             big.Int
	QIntervalBound      bool
	OddResiduePrimes    []int
	PTailUnknownBits    int
	QTailUnknownBits    int
	ArithmeticBits      int
	SkipKnownPrefixBits int
	TailWindowStart     int
	TailWindowBits      int
	TailWindowCarryBits int
	ExactTailCarryLimbs int
	ExactCarryBits      int
	LowliftQBits        int
	Columns             []Column
	CarryVars           []int
	CNF                 CNF
}

type CNF struct {
	nextVar int
	clauses [][]int
	names   map[int]string
	trueVar int
}

func (c *CNF) NewVar(name string) int {
	if c.names == nil {
		c.names = map[int]string{}
	}
	c.nextVar++
	c.names[c.nextVar] = name
	return c.nextVar
}

func (c *CNF) AddClause(lits ...int) {
	cp := make([]int, len(lits))
	copy(cp, lits)
	c.clauses = append(c.clauses, cp)
}

func (c *CNF) TrueLit() int {
	if c.trueVar == 0 {
		c.trueVar = c.NewVar("const_true")
		c.AddClause(c.trueVar)
	}
	return c.trueVar
}

func (c *CNF) RequireLiteralValue(lit int, value bool) {
	if value {
		c.AddClause(lit)
	} else {
		c.AddClause(-lit)
	}
}

func (c *CNF) WriteDIMACS(w io.Writer, comments bool) error {
	if comments {
		for id := 1; id <= c.nextVar; id++ {
			if name, ok := c.names[id]; ok {
				if _, err := fmt.Fprintf(w, "c var %d %s\n", id, name); err != nil {
					return err
				}
			}
		}
	}
	if _, err := fmt.Fprintf(w, "p cnf %d %d\n", c.nextVar, len(c.clauses)); err != nil {
		return err
	}
	for _, clause := range c.clauses {
		for _, lit := range clause {
			if _, err := fmt.Fprintf(w, "%d ", lit); err != nil {
				return err
			}
		}
		if _, err := fmt.Fprintln(w, "0"); err != nil {
			return err
		}
	}
	return nil
}

func (c *CNF) WriteVariableMapJSON(w io.Writer, prefixes []string) error {
	out := map[string]int{}
	for id, name := range c.names {
		for _, prefix := range prefixes {
			if strings.HasPrefix(name, prefix) {
				out[name] = id
				break
			}
		}
	}
	encoder := json.NewEncoder(w)
	encoder.SetIndent("", "  ")
	return encoder.Encode(out)
}

func main() {
	inPath := flag.String("input", "", "JSON input with cube/parameters")
	outPath := flag.String("out", "", "DIMACS output path; stdout when empty")
	varMapPath := flag.String("var-map", "", "JSON output path for p_/q_ DIMACS variable ids")
	summaryOnly := flag.Bool("summary", false, "print model summary without DIMACS")
	noComments := flag.Bool("no-comments", false, "omit variable-name comment lines from DIMACS output")
	flag.Parse()

	if *inPath == "" {
		fmt.Fprintln(os.Stderr, "usage: go run . --input input.json [--out model.cnf]")
		os.Exit(2)
	}

	input, err := loadInput(*inPath)
	if err != nil {
		fatal(err)
	}
	model, err := BuildTailModel(input)
	if err != nil {
		fatal(err)
	}
	printSummary(os.Stderr, model)
	if *summaryOnly {
		return
	}

	var output io.Writer = os.Stdout
	var file *os.File
	if *outPath != "" {
		file, err = os.Create(*outPath)
		if err != nil {
			fatal(err)
		}
		defer file.Close()
		output = file
	}
	if err := model.CNF.WriteDIMACS(output, !*noComments && !input.NoComments); err != nil {
		fatal(err)
	}
	if *varMapPath != "" {
		file, err := os.Create(*varMapPath)
		if err != nil {
			fatal(err)
		}
		defer file.Close()
		if err := model.CNF.WriteVariableMapJSON(file, []string{"p_", "q_"}); err != nil {
			fatal(err)
		}
	}
}

func fatal(err error) {
	fmt.Fprintln(os.Stderr, "error:", err)
	os.Exit(1)
}

func loadInput(path string) (Input, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return Input{}, err
	}
	var input Input
	if err := json.Unmarshal(data, &input); err != nil {
		return Input{}, err
	}
	if len(input.PlanArgv) > 0 {
		if err := applyArgv(&input, input.PlanArgv); err != nil {
			return Input{}, err
		}
	}
	if input.T == 0 {
		input.T = defaultT
	}
	if input.LimbBits == 0 {
		input.LimbBits = defaultLimbBit
	}
	if input.TailLimbs == 0 {
		input.TailLimbs = 8
	}
	if input.AssumptionsAs == "" {
		input.AssumptionsAs = "unit"
	}
	return input, nil
}

func applyArgv(input *Input, argv []string) error {
	for i := 0; i < len(argv); i++ {
		arg := argv[i]
		next := func() (string, error) {
			i++
			if i >= len(argv) {
				return "", fmt.Errorf("%s needs a value", arg)
			}
			return argv[i], nil
		}
		switch arg {
		case "--T":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.T = v
		case "--limb-bits":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.LimbBits = v
		case "--tail-limbs":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.TailLimbs = v
		case "--arith-bits", "--arithmetic-bits":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.ArithmeticBits = v
		case "--skip-known-prefix-limbs":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.SkipKnownPrefixLimbs = v
		case "--skip-known-prefix-bits":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.SkipKnownPrefixBits = v
		case "--tail-window-start":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.TailWindowStart = v
		case "--tail-window-bits":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.TailWindowBits = v
		case "--tail-window-carry-bits":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.TailWindowCarryBits = v
		case "--exact-tail-carry-limbs":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.ExactTailCarryLimbs = v
		case "--exact-carry-bits":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.ExactCarryBits = v
		case "--lowlift-q":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.LowliftQBits = v
		case "--q-interval-bound":
			input.QIntervalBound = true
		case "--no-q-interval-bound":
			input.QIntervalBound = false
		case "--odd-residue-prime":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.OddResiduePrimes = append(input.OddResiduePrimes, v)
		case "--odd-residue-primes":
			text, err := next()
			if err != nil {
				return err
			}
			if strings.TrimSpace(text) == "" {
				break
			}
			for _, part := range strings.Split(text, ",") {
				v, err := strconv.ParseInt(strings.TrimSpace(part), 0, 64)
				if err != nil {
					return err
				}
				input.OddResiduePrimes = append(input.OddResiduePrimes, int(v))
			}
		case "--branch-low":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.BranchLow = v
		case "--branch-high":
			v, err := nextInt(next)
			if err != nil {
				return err
			}
			input.BranchHigh = v
		case "--fix-p-range":
			r, err := nextRange(next)
			if err != nil {
				return err
			}
			input.FixedP = append(input.FixedP, r)
		case "--fix-q-range":
			r, err := nextRange(next)
			if err != nil {
				return err
			}
			input.FixedQ = append(input.FixedQ, r)
		case "--decision-p-range":
			r, err := nextBitRange(next)
			if err != nil {
				return err
			}
			input.DecisionP = append(input.DecisionP, r)
		case "--decision-q-range":
			r, err := nextBitRange(next)
			if err != nil {
				return err
			}
			input.DecisionQ = append(input.DecisionQ, r)
		}
	}
	return nil
}

func nextInt(next func() (string, error)) (int, error) {
	text, err := next()
	if err != nil {
		return 0, err
	}
	v, err := strconv.ParseInt(text, 0, 64)
	return int(v), err
}

func nextRange(next func() (string, error)) (FixedRange, error) {
	text, err := next()
	if err != nil {
		return FixedRange{}, err
	}
	return parseFixedRange(text)
}

func nextBitRange(next func() (string, error)) (BitRange, error) {
	text, err := next()
	if err != nil {
		return BitRange{}, err
	}
	parts := strings.Split(text, ":")
	if len(parts) != 2 {
		return BitRange{}, fmt.Errorf("expected START:WIDTH, got %q", text)
	}
	start, err := strconv.ParseInt(parts[0], 0, 64)
	if err != nil {
		return BitRange{}, err
	}
	width, err := strconv.ParseInt(parts[1], 0, 64)
	if err != nil {
		return BitRange{}, err
	}
	return BitRange{Start: int(start), Width: int(width)}, nil
}

func parseFixedRange(text string) (FixedRange, error) {
	parts := strings.Split(text, ":")
	if len(parts) != 3 {
		return FixedRange{}, fmt.Errorf("expected START:WIDTH:VALUE, got %q", text)
	}
	start, err := strconv.ParseInt(parts[0], 0, 64)
	if err != nil {
		return FixedRange{}, err
	}
	width, err := strconv.ParseInt(parts[1], 0, 64)
	if err != nil {
		return FixedRange{}, err
	}
	var value BigUInt
	if err := value.UnmarshalJSON([]byte(strconv.Quote(parts[2]))); err != nil {
		return FixedRange{}, err
	}
	return FixedRange{Start: int(start), Width: int(width), Value: &value}, nil
}

func BuildTailModel(input Input) (*TailModel, error) {
	if input.T != 784 && input.T != 800 && input.T != 816 && input.T != 832 && input.T != 848 {
		return nil, fmt.Errorf("T must be one of 784, 800, 816, 832, 848 for this prototype")
	}
	if input.LimbBits != defaultLimbBit {
		return nil, fmt.Errorf("only 16-bit limbs are implemented")
	}
	if input.T%input.LimbBits != 0 {
		return nil, fmt.Errorf("T must be limb-aligned")
	}
	if input.N.V.Sign() == 0 {
		return nil, fmt.Errorf("n is required")
	}

	knownP := new(big.Int).Set(&input.KnownP.V)
	maskP := new(big.Int).Set(&input.MaskP.V)
	orSmallShifted(knownP, input.BranchLow&0xf, 150)
	orSmallShifted(knownP, input.BranchHigh&0xf, 920)
	orSmallShifted(maskP, 0xf, 150)
	orSmallShifted(maskP, 0xf, 920)
	for _, fixed := range input.FixedP {
		if err := applyFixed(knownP, maskP, fixed); err != nil {
			return nil, fmt.Errorf("p fixed range: %w", err)
		}
	}

	lower := input.T / input.LimbBits
	model := &TailModel{
		Input:          input,
		LowerLimbCount: lower,
		TotalColumns:   lower + input.TailLimbs,
		CNF:            CNF{},
	}

	lowerMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(input.T)), big.NewInt(1))
	pLowMask := new(big.Int).And(maskP, lowerMask)
	pLowKnown := new(big.Int).And(knownP, lowerMask)
	qKnown, qMask, qPrefixBits, qPrefixStart, qPrefix, qMin, qMax, err := qKnownFromFixed(input, knownP, maskP)
	if err != nil {
		return nil, err
	}
	if input.LowliftQBits == 265 || input.LowliftQBits == 272 {
		liftModulus := new(big.Int).Lsh(big.NewInt(1), uint(input.LowliftQBits))
		liftMask := new(big.Int).Sub(liftModulus, big.NewInt(1))
		if new(big.Int).And(maskP, liftMask).Cmp(liftMask) == 0 {
			pLow := new(big.Int).And(knownP, liftMask)
			inv := new(big.Int).ModInverse(pLow, liftModulus)
			if inv == nil {
				return nil, fmt.Errorf("known p low part is not invertible modulo 2^%d", input.LowliftQBits)
			}
			qLow := new(big.Int).Mul(&input.N.V, inv)
			qLow.Mod(qLow, liftModulus)
			if err := applyKnownBits(qKnown, qMask, qLow, liftMask); err != nil {
				return nil, fmt.Errorf("known q lowlift inconsistent: %w", err)
			}
		}
	}
	qLowMask := new(big.Int).And(qMask, lowerMask)
	qLowKnown := new(big.Int).And(qKnown, lowerMask)

	model.PHigh.Rsh(knownP, uint(input.T))
	model.QHigh.Rsh(qKnown, uint(input.T))
	model.QPrefix.Set(qPrefix)
	model.QPrefixBits = qPrefixBits
	model.QPrefixStart = qPrefixStart
	model.PTailUnknownBits = countUnsetBits(maskP, input.T, pBits-input.T)
	model.QTailUnknownBits = countUnsetBits(qMask, input.T, pBits-input.T)
	if model.PTailUnknownBits != 0 {
		return nil, fmt.Errorf("p tail is not fully known above T; unknown bits above T = %d", model.PTailUnknownBits)
	}
	if model.QTailUnknownBits != 0 {
		return nil, fmt.Errorf("q tail is not fully known above T; unknown bits above T = %d", model.QTailUnknownBits)
	}
	model.PLimbs = buildLimbs(&model.CNF, "p", pLowKnown, pLowMask, lower)
	model.QLimbs = buildLimbs(&model.CNF, "q", qLowKnown, qLowMask, lower)
	model.CarryVars = buildCarryVars(&model.CNF, lower+input.TailLimbs)
	model.Columns = buildColumns(input, model.PLimbs, model.QLimbs, &input.N.V, &model.PHigh, &model.QHigh, model.CarryVars)

	addFixedBitClauses(&model.CNF, model.PLimbs, true)
	addFixedBitClauses(&model.CNF, model.QLimbs, true)
	for _, r := range input.FixedQ {
		addRangeClauses(&model.CNF, model.QLimbs, r)
	}
	skipBits := input.SkipKnownPrefixLimbs * input.LimbBits
	if input.SkipKnownPrefixBits > 0 {
		if input.SkipKnownPrefixLimbs > 0 && skipBits != input.SkipKnownPrefixBits {
			return nil, fmt.Errorf("skip_known_prefix_bits=%d conflicts with skip_known_prefix_limbs=%d", input.SkipKnownPrefixBits, input.SkipKnownPrefixLimbs)
		}
		skipBits = input.SkipKnownPrefixBits
	}
	model.SkipKnownPrefixBits = skipBits
	if input.LowliftQBits != 0 {
		if input.LowliftQBits != 265 && input.LowliftQBits != 272 {
			return nil, fmt.Errorf("lowlift_q_bits currently supports only 265 and 272, got %d", input.LowliftQBits)
		}
		if input.T < input.LowliftQBits {
			return nil, fmt.Errorf("lowlift_q_bits=%d exceeds T=%d", input.LowliftQBits, input.T)
		}
		if input.LowliftQBits == 265 {
			if err := addLowliftQ265Clauses(&model.CNF, model.PLimbs, model.QLimbs, &input.N.V, knownP); err != nil {
				return nil, err
			}
		} else {
			if err := addLowliftQ272Clauses(&model.CNF, model.PLimbs, model.QLimbs, &input.N.V, knownP); err != nil {
				return nil, err
			}
		}
		model.LowliftQBits = input.LowliftQBits
	}
	if input.QIntervalBound {
		qLowMin, qLowMax, err := qLowIntervalBounds(qMin, qMax, &model.QHigh, input.T)
		if err != nil {
			return nil, err
		}
		model.QLowMin.Set(qLowMin)
		model.QLowMax.Set(qLowMax)
		model.QIntervalBound = true
		addUnsignedBounds(&model.CNF, model.QLimbs, input.T, qLowMin, qLowMax)
	}
	if input.ArithmeticBits > 0 {
		if input.ArithmeticBits > productBits {
			return nil, fmt.Errorf("arithmetic_bits=%d exceeds supported product prefix width %d", input.ArithmeticBits, productBits)
		}
		if err := addArithmeticPrefixClauses(&model.CNF, model.PLimbs, model.QLimbs, &model.PHigh, &model.QHigh, &input.N.V, input.T, input.ArithmeticBits, skipBits); err != nil {
			return nil, err
		}
		model.ArithmeticBits = input.ArithmeticBits
	}
	if input.TailWindowBits > 0 {
		start := input.TailWindowStart
		if start == 0 {
			start = input.T
		}
		carryBits := input.TailWindowCarryBits
		if carryBits == 0 {
			carryBits = 12
		}
		if err := addArithmeticWindowClauses(&model.CNF, model.PLimbs, model.QLimbs, &model.PHigh, &model.QHigh, &input.N.V, input.T, start, input.TailWindowBits, carryBits); err != nil {
			return nil, err
		}
		model.TailWindowStart = start
		model.TailWindowBits = input.TailWindowBits
		model.TailWindowCarryBits = carryBits
	}
	if input.ExactTailCarryLimbs > 0 {
		if input.ExactTailCarryLimbs > input.TailLimbs {
			return nil, fmt.Errorf("exact_tail_carry_limbs=%d exceeds tail_limbs=%d", input.ExactTailCarryLimbs, input.TailLimbs)
		}
		if skipBits%input.LimbBits != 0 {
			return nil, fmt.Errorf("exact carry-column encoding requires limb-aligned skip_known_prefix_bits, got %d", skipBits)
		}
		startColumn := skipBits / input.LimbBits
		carryBits := input.ExactCarryBits
		if carryBits == 0 {
			carryBits = 32
		}
		exactColumns := lower + input.ExactTailCarryLimbs
		if startColumn > exactColumns {
			return nil, fmt.Errorf("skip_known_prefix_bits=%d skips past exact carry columns=%d", skipBits, exactColumns)
		}
		initialCarry := big.NewInt(0)
		if skipBits > 0 {
			carry, err := knownPrefixCarry(model.PLimbs, model.QLimbs, &input.N.V, skipBits)
			if err != nil {
				return nil, fmt.Errorf("exact carry known prefix: %w", err)
			}
			initialCarry = carry
		}
		if err := addExactCarryColumnClauses(&model.CNF, model.Columns[:exactColumns], carryBits, startColumn, initialCarry); err != nil {
			return nil, err
		}
		model.ExactTailCarryLimbs = input.ExactTailCarryLimbs
		model.ExactCarryBits = carryBits
	}
	if len(input.OddResiduePrimes) > 0 {
		if err := addOddResidueClauses(&model.CNF, model.PLimbs, model.QLimbs, &model.PHigh, &model.QHigh, &input.N.V, input.T, input.OddResiduePrimes); err != nil {
			return nil, err
		}
		model.OddResiduePrimes = append(model.OddResiduePrimes, input.OddResiduePrimes...)
	}
	return model, nil
}

func qKnownFromFixed(input Input, knownP, maskP *big.Int) (*big.Int, *big.Int, int, int, *big.Int, *big.Int, *big.Int, error) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	unknown := new(big.Int).AndNot(fullMask, maskP)
	lowKnownBits := pBits
	for bit := 0; bit < pBits; bit++ {
		if unknown.Bit(bit) == 1 {
			lowKnownBits = bit
			break
		}
	}
	if lowKnownBits > input.T {
		lowKnownBits = input.T
	}

	qKnown := new(big.Int)
	qMask := new(big.Int)
	if lowKnownBits > 0 {
		modulus := new(big.Int).Lsh(big.NewInt(1), uint(lowKnownBits))
		pLow := new(big.Int).And(knownP, new(big.Int).Sub(modulus, big.NewInt(1)))
		inv := new(big.Int).ModInverse(pLow, modulus)
		if inv == nil {
			return nil, nil, 0, 0, nil, nil, nil, fmt.Errorf("known p low part is not invertible modulo 2^%d", lowKnownBits)
		}
		qKnown.Mod(new(big.Int).Mul(&input.N.V, inv), modulus)
		qMask.Sub(modulus, big.NewInt(1))
	}

	pMin := new(big.Int).Set(knownP)
	pMax := new(big.Int).Or(new(big.Int).Set(knownP), unknown)
	if pMin.Sign() <= 0 || pMax.Sign() <= 0 {
		return nil, nil, 0, 0, nil, nil, nil, fmt.Errorf("invalid p interval")
	}
	qMin := new(big.Int).Quo(&input.N.V, pMax)
	qMax := new(big.Int).Quo(&input.N.V, pMin)
	qPrefixBits, qPrefix, qPrefixStart := commonPrefix(qMin, qMax, pBits)
	if qPrefixBits > 0 {
		prefixMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(qPrefixBits)), big.NewInt(1))
		prefixMask.Lsh(prefixMask, uint(qPrefixStart))
		prefixBits := new(big.Int).Lsh(qPrefix, uint(qPrefixStart))
		if err := applyKnownBits(qKnown, qMask, prefixBits, prefixMask); err != nil {
			return nil, nil, 0, 0, nil, nil, nil, fmt.Errorf("q prefix inconsistent: %w", err)
		}
	}

	for _, fixed := range input.FixedQ {
		if err := applyFixed(qKnown, qMask, fixed); err != nil {
			return nil, nil, 0, 0, nil, nil, nil, fmt.Errorf("q fixed range: %w", err)
		}
	}
	return qKnown, qMask, qPrefixBits, qPrefixStart, qPrefix, qMin, qMax, nil
}

func applyFixed(known, mask *big.Int, fixed FixedRange) error {
	if fixed.Value == nil {
		return fmt.Errorf("missing value")
	}
	if fixed.Start < 0 || fixed.Width <= 0 || fixed.Start+fixed.Width > pBits {
		return fmt.Errorf("invalid range %d:%d", fixed.Start, fixed.Width)
	}
	limit := new(big.Int).Lsh(big.NewInt(1), uint(fixed.Width))
	if fixed.Value.V.Cmp(limit) >= 0 {
		return fmt.Errorf("value %s does not fit width %d", fixed.Value.String(), fixed.Width)
	}
	rangeMask := new(big.Int).Sub(limit, big.NewInt(1))
	rangeMask.Lsh(rangeMask, uint(fixed.Start))
	bits := new(big.Int).Lsh(&fixed.Value.V, uint(fixed.Start))
	if err := applyKnownBits(known, mask, bits, rangeMask); err != nil {
		return err
	}
	return nil
}

func applyKnownBits(known, mask, bits, rangeMask *big.Int) error {
	overlap := new(big.Int).And(mask, rangeMask)
	oldOverlap := new(big.Int).And(known, overlap)
	newOverlap := new(big.Int).And(bits, overlap)
	if oldOverlap.Cmp(newOverlap) != 0 {
		return fmt.Errorf("inconsistent fixed bits")
	}
	known.Or(known, bits)
	mask.Or(mask, rangeMask)
	return nil
}

func commonPrefix(lo, hi *big.Int, bits int) (int, *big.Int, int) {
	if lo.Cmp(hi) > 0 {
		lo, hi = hi, lo
	}
	diff := new(big.Int).Xor(lo, hi)
	prefixBits := bits
	if diff.Sign() != 0 {
		prefixBits = bits - diff.BitLen()
	}
	prefixStart := bits - prefixBits
	prefix := new(big.Int).Rsh(lo, uint(prefixStart))
	return prefixBits, prefix, prefixStart
}

func countUnsetBits(mask *big.Int, start, width int) int {
	if width <= 0 {
		return 0
	}
	count := 0
	for bit := start; bit < start+width; bit++ {
		if mask.Bit(bit) == 0 {
			count++
		}
	}
	return count
}

func buildLimbs(cnf *CNF, name string, known, mask *big.Int, count int) []LimbRef {
	limbs := make([]LimbRef, count)
	for i := range limbs {
		limb := LimbRef{Name: name, Index: i}
		for bit := 0; bit < defaultLimbBit; bit++ {
			globalBit := i*defaultLimbBit + bit
			if mask.Bit(globalBit) == 1 {
				limb.KnownMask |= 1 << bit
				if known.Bit(globalBit) == 1 {
					limb.KnownValue |= 1 << bit
				}
			}
			limb.BitVars[bit] = cnf.NewVar(fmt.Sprintf("%s_%d", name, globalBit))
		}
		limbs[i] = limb
	}
	return limbs
}

func buildCarryVars(cnf *CNF, columns int) []int {
	carries := make([]int, columns+1)
	for i := range carries {
		carries[i] = cnf.NewVar(fmt.Sprintf("carry_nonzero_marker_%d", i))
	}
	return carries
}

func buildColumns(input Input, pLimbs, qLimbs []LimbRef, n, pHigh, qHigh *big.Int, carries []int) []Column {
	baseMask := uint64(0xffff)
	lower := len(pLimbs)
	cols := make([]Column, 0, lower+input.TailLimbs)
	pHighLimbs := intLimbs(pHigh, input.LimbBits)
	qHighLimbs := intLimbs(qHigh, input.LimbBits)
	highProduct := new(big.Int).Mul(pHigh, qHigh)
	highProductLimbs := intLimbs(highProduct, input.LimbBits)

	for col := 0; col < lower+input.TailLimbs; col++ {
		target := uint16(new(big.Int).Rsh(n, uint(col*input.LimbBits)).Uint64() & baseMask)
		column := Column{Index: col, TargetLimb: target, Const: big.NewInt(0), CarryIn: carries[col], CarryOut: carries[col+1], Tail: col >= lower}
		lo := max(0, col-lower+1)
		hi := min(lower-1, col)
		for i := lo; i <= hi; i++ {
			column.Terms = append(column.Terms, ProductTerm{P: pLimbs[i], Q: qLimbs[col-i], Source: "low_low"})
		}
		if col >= lower {
			tailIndex := col - lower
			for i, q := range qLimbs {
				h := tailIndex - i
				if h >= 0 && h < len(pHighLimbs) && pHighLimbs[h] != 0 {
					column.Terms = append(column.Terms, ProductTerm{Q: q, Coeff: pHighLimbs[h], Source: "p_high_q_low"})
				}
			}
			for i, p := range pLimbs {
				h := tailIndex - i
				if h >= 0 && h < len(qHighLimbs) && qHighLimbs[h] != 0 {
					column.Terms = append(column.Terms, ProductTerm{P: p, Coeff: qHighLimbs[h], Source: "q_high_p_low"})
				}
			}
			if tailIndex >= lower {
				productIndex := tailIndex - lower
				if productIndex < len(highProductLimbs) {
					column.Const.Add(column.Const, new(big.Int).SetUint64(highProductLimbs[productIndex]))
				}
			}
		}
		cols = append(cols, column)
	}
	return cols
}

func intLimbs(value *big.Int, bits int) []uint64 {
	if value.Sign() == 0 {
		return []uint64{0}
	}
	count := (value.BitLen() + bits - 1) / bits
	limbs := make([]uint64, count)
	mask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(bits)), big.NewInt(1))
	for i := 0; i < count; i++ {
		limbs[i] = new(big.Int).And(new(big.Int).Rsh(value, uint(i*bits)), mask).Uint64()
	}
	return limbs
}

func addFixedBitClauses(cnf *CNF, limbs []LimbRef, asUnits bool) {
	if !asUnits {
		return
	}
	for _, limb := range limbs {
		for bit := 0; bit < defaultLimbBit; bit++ {
			if (limb.KnownMask>>bit)&1 == 0 {
				continue
			}
			lit := limb.BitVars[bit]
			if (limb.KnownValue>>bit)&1 == 0 {
				lit = -lit
			}
			cnf.AddClause(lit)
		}
	}
}

func addRangeClauses(cnf *CNF, limbs []LimbRef, r FixedRange) {
	if r.Value == nil {
		return
	}
	for off := 0; off < r.Width; off++ {
		bit := r.Start + off
		limbIndex := bit / defaultLimbBit
		limbBit := bit % defaultLimbBit
		if limbIndex < 0 || limbIndex >= len(limbs) {
			continue
		}
		lit := limbs[limbIndex].BitVars[limbBit]
		if r.Value.V.Bit(off) == 0 {
			lit = -lit
		}
		cnf.AddClause(lit)
	}
}

func qLowIntervalBounds(qMin, qMax, qHigh *big.Int, t int) (*big.Int, *big.Int, error) {
	qHighShifted := new(big.Int).Lsh(new(big.Int).Set(qHigh), uint(t))
	lo := new(big.Int).Sub(qMin, qHighShifted)
	hi := new(big.Int).Sub(qMax, qHighShifted)
	zero := big.NewInt(0)
	if lo.Sign() < 0 {
		lo.Set(zero)
	}
	maxLow := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(t)), big.NewInt(1))
	if hi.Cmp(maxLow) > 0 {
		hi.Set(maxLow)
	}
	if hi.Sign() < 0 || lo.Cmp(maxLow) > 0 || lo.Cmp(hi) > 0 {
		return nil, nil, fmt.Errorf("q lower interval is empty after high-tail split")
	}
	return lo, hi, nil
}

func addUnsignedBounds(cnf *CNF, limbs []LimbRef, bits int, lo, hi *big.Int) {
	addLowerBound(cnf, limbs, bits, lo)
	addUpperBound(cnf, limbs, bits, hi)
}

func addUpperBound(cnf *CNF, limbs []LimbRef, bits int, bound *big.Int) {
	for bit := bits - 1; bit >= 0; bit-- {
		if bound.Bit(bit) == 1 {
			continue
		}
		clause := prefixInequalityClause(cnf, limbs, bits, bound, bit)
		clause = append(clause, -factorLowerBitLit(cnf, limbs, bit))
		addSimplifiedClause(cnf, clause)
	}
}

func addLowerBound(cnf *CNF, limbs []LimbRef, bits int, bound *big.Int) {
	for bit := bits - 1; bit >= 0; bit-- {
		if bound.Bit(bit) == 0 {
			continue
		}
		clause := prefixInequalityClause(cnf, limbs, bits, bound, bit)
		clause = append(clause, factorLowerBitLit(cnf, limbs, bit))
		addSimplifiedClause(cnf, clause)
	}
}

func prefixInequalityClause(cnf *CNF, limbs []LimbRef, bits int, bound *big.Int, belowBit int) []int {
	clause := []int{}
	for bit := bits - 1; bit > belowBit; bit-- {
		lit := factorLowerBitLit(cnf, limbs, bit)
		if bound.Bit(bit) == 1 {
			clause = append(clause, -lit)
		} else {
			clause = append(clause, lit)
		}
	}
	return clause
}

func factorLowerBitLit(cnf *CNF, limbs []LimbRef, bit int) int {
	trueLit := cnf.TrueLit()
	limbIndex := bit / defaultLimbBit
	limbBit := bit % defaultLimbBit
	if limbIndex < 0 || limbIndex >= len(limbs) {
		return -trueLit
	}
	limb := limbs[limbIndex]
	if (limb.KnownMask>>limbBit)&1 == 1 {
		if (limb.KnownValue>>limbBit)&1 == 1 {
			return trueLit
		}
		return -trueLit
	}
	return limb.BitVars[limbBit]
}

func addSimplifiedClause(cnf *CNF, lits []int) {
	trueLit := cnf.TrueLit()
	out := []int{}
	seen := map[int]bool{}
	for _, lit := range lits {
		if lit == trueLit {
			return
		}
		if lit == -trueLit {
			continue
		}
		if seen[-lit] {
			return
		}
		if !seen[lit] {
			seen[lit] = true
			out = append(out, lit)
		}
	}
	cnf.AddClause(out...)
}

func requireEqualLits(cnf *CNF, a, b int) {
	trueLit := cnf.TrueLit()
	if a == b {
		return
	}
	if a == -b {
		cnf.AddClause()
		return
	}
	switch a {
	case trueLit:
		cnf.RequireLiteralValue(b, true)
		return
	case -trueLit:
		cnf.RequireLiteralValue(b, false)
		return
	}
	switch b {
	case trueLit:
		cnf.RequireLiteralValue(a, true)
		return
	case -trueLit:
		cnf.RequireLiteralValue(a, false)
		return
	}
	cnf.AddClause(-a, b)
	cnf.AddClause(a, -b)
}

func addArithmeticPrefixClauses(cnf *CNF, pLimbs, qLimbs []LimbRef, pHigh, qHigh, n *big.Int, splitBit, bits, skipBits int) error {
	if bits < 0 || splitBit != len(pLimbs)*defaultLimbBit || splitBit != len(qLimbs)*defaultLimbBit {
		return fmt.Errorf("invalid arithmetic_bits=%d for %d p limbs and %d q limbs", bits, len(pLimbs), len(qLimbs))
	}
	if bits > productBits {
		return fmt.Errorf("arithmetic_bits=%d exceeds supported product prefix width %d", bits, productBits)
	}
	if skipBits < 0 || skipBits > splitBit || skipBits > bits {
		return fmt.Errorf("invalid skip_known_prefix bits %d for split=%d arithmetic_bits=%d", skipBits, splitBit, bits)
	}
	columns := make([][]int, bits)
	if skipBits > 0 {
		carry, err := knownPrefixCarry(pLimbs, qLimbs, n, skipBits)
		if err != nil {
			return err
		}
		addCarryBits(cnf, columns, carry, skipBits)
	}
	factorWidth := min(bits, pBits)
	for i := 0; i < factorWidth; i++ {
		pLit := factorBitLit(cnf, pLimbs, pHigh, splitBit, i)
		for j := 0; j < factorWidth && j+i < bits; j++ {
			if i < skipBits && j < skipBits {
				continue
			}
			qLit := factorBitLit(cnf, qLimbs, qHigh, splitBit, j)
			product := productLit(cnf, pLit, qLit, fmt.Sprintf("mul_%d_%d", i, j))
			if product != 0 {
				columns[i+j] = append(columns[i+j], product)
			}
		}
	}

	for bit := skipBits; bit < bits; bit++ {
		for len(columns[bit]) > 2 {
			nTerms := len(columns[bit])
			a := columns[bit][nTerms-1]
			b := columns[bit][nTerms-2]
			d := columns[bit][nTerms-3]
			columns[bit] = columns[bit][:nTerms-3]
			sum, carry := fullAdderLits(cnf, a, b, d, fmt.Sprintf("%d_%d", bit, len(columns[bit])))
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < bits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		if len(columns[bit]) == 2 {
			a := columns[bit][0]
			b := columns[bit][1]
			sum, carry := halfAdderLits(cnf, a, b, fmt.Sprintf("%d", bit))
			columns[bit] = nil
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < bits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		target := n.Bit(bit) == 1
		if len(columns[bit]) == 0 {
			if target {
				cnf.AddClause()
			}
			continue
		}
		cnf.RequireLiteralValue(columns[bit][0], target)
	}
	return nil
}

func addArithmeticWindowClauses(cnf *CNF, pLimbs, qLimbs []LimbRef, pHigh, qHigh, n *big.Int, splitBit, startBit, bits, carryBits int) error {
	if bits <= 0 {
		return nil
	}
	if splitBit != len(pLimbs)*defaultLimbBit || splitBit != len(qLimbs)*defaultLimbBit {
		return fmt.Errorf("invalid split bit %d for %d p limbs and %d q limbs", splitBit, len(pLimbs), len(qLimbs))
	}
	if startBit < 0 || startBit >= productBits {
		return fmt.Errorf("invalid tail_window_start=%d", startBit)
	}
	if startBit+bits > productBits {
		return fmt.Errorf("tail window [%d,%d) exceeds product width %d", startBit, startBit+bits, productBits)
	}
	if carryBits < 0 || carryBits > 16 {
		return fmt.Errorf("tail_window_carry_bits=%d outside supported range 0..16", carryBits)
	}

	columns := make([][]int, bits)
	for bit := 0; bit < carryBits && bit < bits; bit++ {
		columns[bit] = append(columns[bit], cnf.NewVar(fmt.Sprintf("tail_window_carry_in_%d_%d", startBit, bit)))
	}

	factorWidth := min(startBit+bits, pBits)
	for i := 0; i < factorWidth; i++ {
		pLit := factorBitLit(cnf, pLimbs, pHigh, splitBit, i)
		minJ := startBit - i
		if minJ < 0 {
			minJ = 0
		}
		maxJ := startBit + bits - 1 - i
		if maxJ >= pBits {
			maxJ = pBits - 1
		}
		for j := minJ; j <= maxJ; j++ {
			col := i + j - startBit
			qLit := factorBitLit(cnf, qLimbs, qHigh, splitBit, j)
			product := productLit(cnf, pLit, qLit, fmt.Sprintf("tail_mul_%d_%d", i, j))
			if product != 0 {
				columns[col] = append(columns[col], product)
			}
		}
	}

	for bit := 0; bit < bits; bit++ {
		for len(columns[bit]) > 2 {
			nTerms := len(columns[bit])
			a := columns[bit][nTerms-1]
			b := columns[bit][nTerms-2]
			d := columns[bit][nTerms-3]
			columns[bit] = columns[bit][:nTerms-3]
			sum, carry := fullAdderLits(cnf, a, b, d, fmt.Sprintf("tail_%d_%d", startBit+bit, len(columns[bit])))
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < bits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		if len(columns[bit]) == 2 {
			a := columns[bit][0]
			b := columns[bit][1]
			sum, carry := halfAdderLits(cnf, a, b, fmt.Sprintf("tail_%d", startBit+bit))
			columns[bit] = nil
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < bits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		target := n.Bit(startBit+bit) == 1
		if len(columns[bit]) == 0 {
			if target {
				cnf.AddClause()
			}
			continue
		}
		cnf.RequireLiteralValue(columns[bit][0], target)
	}
	return nil
}

func addExactCarryColumnClauses(cnf *CNF, columns []Column, carryBits int, startColumn int, initialCarry *big.Int) error {
	if carryBits <= 0 || carryBits > 512 {
		return fmt.Errorf("exact carry bits must be in 1..512, got %d", carryBits)
	}
	if startColumn < 0 || startColumn > len(columns) {
		return fmt.Errorf("exact carry start column %d outside 0..%d", startColumn, len(columns))
	}
	if initialCarry == nil {
		initialCarry = big.NewInt(0)
	}
	if initialCarry.Sign() < 0 || initialCarry.BitLen() > carryBits {
		return fmt.Errorf("initial exact carry 0x%s does not fit %d bits", initialCarry.Text(16), carryBits)
	}
	carryWidths, err := exactCarryWidths(columns, carryBits, startColumn, initialCarry)
	if err != nil {
		return err
	}
	trueLit := cnf.TrueLit()
	carries := make([][]int, len(columns)+1)
	for col := startColumn; col < len(carries); col++ {
		carries[col] = make([]int, carryWidths[col])
		for bit := range carries[col] {
			if col == startColumn {
				carries[col][bit] = -trueLit
				if initialCarry.Bit(bit) == 1 {
					carries[col][bit] = trueLit
				}
				continue
			}
			carries[col][bit] = cnf.NewVar(fmt.Sprintf("exact_carry_%d_%d", col, bit))
		}
	}

	for colIndex := startColumn; colIndex < len(columns); colIndex++ {
		column := columns[colIndex]
		bitColumns := make([][]int, defaultLimbBit+carryWidths[colIndex]+defaultLimbBit)
		for bit, carryLit := range carries[colIndex] {
			appendColumnLit(cnf, &bitColumns[bit], carryLit)
		}
		columnConst := new(big.Int).Set(column.Const)
		for termIndex, term := range column.Terms {
			switch term.Source {
			case "low_low":
				if limbFullyKnown(term.P) && limbFullyKnown(term.Q) {
					value := uint64(term.P.KnownValue) * uint64(term.Q.KnownValue)
					columnConst.Add(columnConst, new(big.Int).SetUint64(value))
					continue
				}
				if limbFullyKnown(term.P) {
					addCoeffLimbTerm(cnf, &bitColumns, uint64(term.P.KnownValue), term.Q, fmt.Sprintf("exact_col_%d_term_%d", colIndex, termIndex), trueLit)
					continue
				}
				if limbFullyKnown(term.Q) {
					addCoeffLimbTerm(cnf, &bitColumns, uint64(term.Q.KnownValue), term.P, fmt.Sprintf("exact_col_%d_term_%d", colIndex, termIndex), trueLit)
					continue
				}
				for pBit := 0; pBit < defaultLimbBit; pBit++ {
					pLit := limbBitLit(term.P, pBit, trueLit)
					for qBit := 0; qBit < defaultLimbBit; qBit++ {
						qLit := limbBitLit(term.Q, qBit, trueLit)
						product := productLit(cnf, pLit, qLit, fmt.Sprintf("exact_col_%d_term_%d_mul_%d_%d", colIndex, termIndex, pBit, qBit))
						if product == 0 {
							continue
						}
						bit := pBit + qBit
						for bit >= len(bitColumns) {
							bitColumns = append(bitColumns, nil)
						}
						appendColumnLit(cnf, &bitColumns[bit], product)
					}
				}
			case "p_high_q_low":
				if limbFullyKnown(term.Q) {
					value := term.Coeff * uint64(term.Q.KnownValue)
					columnConst.Add(columnConst, new(big.Int).SetUint64(value))
					continue
				}
				addCoeffLimbTerm(cnf, &bitColumns, term.Coeff, term.Q, fmt.Sprintf("exact_col_%d_term_%d", colIndex, termIndex), trueLit)
			case "q_high_p_low":
				if limbFullyKnown(term.P) {
					value := term.Coeff * uint64(term.P.KnownValue)
					columnConst.Add(columnConst, new(big.Int).SetUint64(value))
					continue
				}
				addCoeffLimbTerm(cnf, &bitColumns, term.Coeff, term.P, fmt.Sprintf("exact_col_%d_term_%d", colIndex, termIndex), trueLit)
			default:
				return fmt.Errorf("unsupported product term source %q in column %d", term.Source, colIndex)
			}
		}
		for bit := 0; bit < columnConst.BitLen(); bit++ {
			if columnConst.Bit(bit) == 0 {
				continue
			}
			for bit >= len(bitColumns) {
				bitColumns = append(bitColumns, nil)
			}
			appendColumnLit(cnf, &bitColumns[bit], trueLit)
		}

		for bit := 0; bit < len(bitColumns); bit++ {
			for len(bitColumns[bit]) > 2 {
				nTerms := len(bitColumns[bit])
				a := bitColumns[bit][nTerms-1]
				b := bitColumns[bit][nTerms-2]
				d := bitColumns[bit][nTerms-3]
				bitColumns[bit] = bitColumns[bit][:nTerms-3]
				sum, carry := fullAdderLits(cnf, a, b, d, fmt.Sprintf("exact_col_%d_bit_%d_%d", colIndex, bit, len(bitColumns[bit])))
				appendColumnLit(cnf, &bitColumns[bit], sum)
				if bit+1 >= len(bitColumns) {
					bitColumns = append(bitColumns, nil)
				}
				appendColumnLit(cnf, &bitColumns[bit+1], carry)
			}
			if len(bitColumns[bit]) == 2 {
				a := bitColumns[bit][0]
				b := bitColumns[bit][1]
				sum, carry := halfAdderLits(cnf, a, b, fmt.Sprintf("exact_col_%d_bit_%d", colIndex, bit))
				bitColumns[bit] = nil
				appendColumnLit(cnf, &bitColumns[bit], sum)
				if bit+1 >= len(bitColumns) {
					bitColumns = append(bitColumns, nil)
				}
				appendColumnLit(cnf, &bitColumns[bit+1], carry)
			}
			sumLit := -trueLit
			if len(bitColumns[bit]) != 0 {
				sumLit = bitColumns[bit][0]
			}
			if bit < defaultLimbBit {
				cnf.RequireLiteralValue(sumLit, (column.TargetLimb>>bit)&1 == 1)
				continue
			}
			carryBit := bit - defaultLimbBit
			if carryBit < len(carries[colIndex+1]) {
				requireEqualLits(cnf, sumLit, carries[colIndex+1][carryBit])
				continue
			}
			cnf.RequireLiteralValue(sumLit, false)
		}
	}
	return nil
}

func addCoeffLimbTerm(cnf *CNF, bitColumns *[][]int, coeff uint64, limb LimbRef, name string, trueLit int) {
	if coeff == 0 {
		return
	}
	for coeffBit := 0; coeffBit < 64; coeffBit++ {
		if (coeff>>coeffBit)&1 == 0 {
			continue
		}
		for limbBit := 0; limbBit < defaultLimbBit; limbBit++ {
			lit := limbBitLit(limb, limbBit, trueLit)
			bit := coeffBit + limbBit
			for bit >= len(*bitColumns) {
				*bitColumns = append(*bitColumns, nil)
			}
			appendColumnLit(cnf, &(*bitColumns)[bit], lit)
		}
	}
}

func limbBitLit(limb LimbRef, bit int, trueLit int) int {
	if (limb.KnownMask>>bit)&1 == 1 {
		if (limb.KnownValue>>bit)&1 == 1 {
			return trueLit
		}
		return -trueLit
	}
	return limb.BitVars[bit]
}

func limbFullyKnown(limb LimbRef) bool {
	return limb.KnownMask == 0xffff
}

func exactCarryWidths(columns []Column, carryBits, startColumn int, initialCarry *big.Int) ([]int, error) {
	widths := make([]int, len(columns)+1)
	carryMax := new(big.Int).Set(initialCarry)
	for colIndex := startColumn; colIndex < len(columns); colIndex++ {
		if carryMax.BitLen() > carryBits {
			return nil, fmt.Errorf("exact carry into column %d needs %d bits, cap is %d", colIndex, carryMax.BitLen(), carryBits)
		}
		widths[colIndex] = carryMax.BitLen()
		columnMax := new(big.Int).Set(carryMax)
		if columns[colIndex].Const.Sign() > 0 {
			columnMax.Add(columnMax, columns[colIndex].Const)
		}
		for _, term := range columns[colIndex].Terms {
			columnMax.Add(columnMax, termMaxValue(term))
		}
		carryMax = new(big.Int).Rsh(columnMax, defaultLimbBit)
	}
	if carryMax.BitLen() > carryBits {
		return nil, fmt.Errorf("exact carry out of final column needs %d bits, cap is %d", carryMax.BitLen(), carryBits)
	}
	widths[len(columns)] = carryMax.BitLen()
	return widths, nil
}

func termMaxValue(term ProductTerm) *big.Int {
	switch term.Source {
	case "low_low":
		return new(big.Int).SetUint64(limbMaxValue(term.P) * limbMaxValue(term.Q))
	case "p_high_q_low":
		return new(big.Int).SetUint64(term.Coeff * limbMaxValue(term.Q))
	case "q_high_p_low":
		return new(big.Int).SetUint64(term.Coeff * limbMaxValue(term.P))
	default:
		return big.NewInt(0)
	}
}

func limbMaxValue(limb LimbRef) uint64 {
	return uint64(limb.KnownValue) | (uint64(^limb.KnownMask) & 0xffff)
}

func appendColumnLit(cnf *CNF, column *[]int, lit int) {
	if lit == -cnf.TrueLit() {
		return
	}
	*column = append(*column, lit)
}

func knownPrefixCarry(pLimbs, qLimbs []LimbRef, n *big.Int, bits int) (*big.Int, error) {
	prefixMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(bits)), big.NewInt(1))
	pValue, err := knownPrefixValue(pLimbs, bits)
	if err != nil {
		return nil, fmt.Errorf("p skip prefix: %w", err)
	}
	qValue, err := knownPrefixValue(qLimbs, bits)
	if err != nil {
		return nil, fmt.Errorf("q skip prefix: %w", err)
	}
	product := new(big.Int).Mul(pValue, qValue)
	target := new(big.Int).And(n, prefixMask)
	diff := new(big.Int).Sub(product, target)
	modulus := new(big.Int).Lsh(big.NewInt(1), uint(bits))
	if new(big.Int).Mod(diff, modulus).Sign() != 0 {
		return nil, fmt.Errorf("known prefix product is not congruent to N modulo 2^%d", bits)
	}
	if diff.Sign() < 0 {
		return nil, fmt.Errorf("known prefix carry would be negative")
	}
	return diff.Rsh(diff, uint(bits)), nil
}

func knownPrefixValue(limbs []LimbRef, bits int) (*big.Int, error) {
	value := new(big.Int)
	for bit := 0; bit < bits; bit++ {
		limbIndex := bit / defaultLimbBit
		limbBit := bit % defaultLimbBit
		if limbIndex < 0 || limbIndex >= len(limbs) {
			return nil, fmt.Errorf("bit %d outside lower limbs", bit)
		}
		limb := limbs[limbIndex]
		if (limb.KnownMask>>limbBit)&1 == 0 {
			return nil, fmt.Errorf("bit %d is not known", bit)
		}
		if (limb.KnownValue>>limbBit)&1 == 1 {
			value.SetBit(value, bit, 1)
		}
	}
	return value, nil
}

func addLowliftQ265Clauses(cnf *CNF, pLimbs, qLimbs []LimbRef, n, knownP *big.Int) error {
	const (
		x1Start  = 210
		x1Width  = 39
		qMidBits = 55
		liftBits = 265
	)
	if len(pLimbs)*defaultLimbBit < liftBits || len(qLimbs)*defaultLimbBit < liftBits {
		return fmt.Errorf("lowlift q=265 requires lower limbs through bit 264")
	}
	liftModulus := new(big.Int).Lsh(big.NewInt(1), liftBits)
	x1Mask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), x1Width), big.NewInt(1))
	x1Mask.Lsh(x1Mask, x1Start)
	p0 := new(big.Int).And(knownP, new(big.Int).Sub(liftModulus, big.NewInt(1)))
	p0.AndNot(p0, x1Mask)
	invP0 := new(big.Int).ModInverse(p0, liftModulus)
	if invP0 == nil {
		return fmt.Errorf("lowlift q=265 p0 is not invertible")
	}
	q0 := new(big.Int).Mul(n, invP0)
	q0.Mod(q0, liftModulus)
	q0Mid := new(big.Int).Rsh(q0, x1Start)
	midModulus := new(big.Int).Lsh(big.NewInt(1), qMidBits)
	q0Mid.And(q0Mid, new(big.Int).Sub(midModulus, big.NewInt(1)))

	cMid := new(big.Int).Mul(n, invP0)
	cMid.Mul(cMid, invP0)
	cMid.Neg(cMid)
	cMid.Mod(cMid, midModulus)

	columns := make([][]int, qMidBits)
	trueLit := cnf.TrueLit()
	for bit := 0; bit < qMidBits; bit++ {
		if q0Mid.Bit(bit) == 1 {
			columns[bit] = append(columns[bit], trueLit)
		}
	}
	for offset := 0; offset < x1Width; offset++ {
		xLit := factorLowerBitLit(cnf, pLimbs, x1Start+offset)
		if xLit == -trueLit {
			continue
		}
		coeff := new(big.Int).Lsh(cMid, uint(offset))
		coeff.Mod(coeff, midModulus)
		for bit := 0; bit < qMidBits; bit++ {
			if coeff.Bit(bit) == 1 {
				columns[bit] = append(columns[bit], xLit)
			}
		}
	}

	for bit := 0; bit < qMidBits; bit++ {
		for len(columns[bit]) > 2 {
			nTerms := len(columns[bit])
			a := columns[bit][nTerms-1]
			b := columns[bit][nTerms-2]
			d := columns[bit][nTerms-3]
			columns[bit] = columns[bit][:nTerms-3]
			sum, carry := fullAdderLits(cnf, a, b, d, fmt.Sprintf("lowlift265_%d_%d", bit, len(columns[bit])))
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < qMidBits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		if len(columns[bit]) == 2 {
			a := columns[bit][0]
			b := columns[bit][1]
			sum, carry := halfAdderLits(cnf, a, b, fmt.Sprintf("lowlift265_%d", bit))
			columns[bit] = nil
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < qMidBits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		sumLit := -trueLit
		if len(columns[bit]) != 0 {
			sumLit = columns[bit][0]
		}
		qLit := factorLowerBitLit(cnf, qLimbs, x1Start+bit)
		requireEqualLits(cnf, sumLit, qLit)
	}
	return nil
}

func addLowliftQ272Clauses(cnf *CNF, pLimbs, qLimbs []LimbRef, n, knownP *big.Int) error {
	const liftBits = 272
	if len(pLimbs)*defaultLimbBit < liftBits || len(qLimbs)*defaultLimbBit < liftBits {
		return fmt.Errorf("lowlift q=272 requires lower limbs through bit 271")
	}
	liftModulus := new(big.Int).Lsh(big.NewInt(1), liftBits)
	liftMask := new(big.Int).Sub(liftModulus, big.NewInt(1))
	p0 := new(big.Int).And(knownP, liftMask)

	type variableBit struct {
		bit int
		lit int
	}
	variableBits := []variableBit{}
	for bit := 0; bit < liftBits; bit++ {
		limb := pLimbs[bit/defaultLimbBit]
		limbBit := bit % defaultLimbBit
		if (limb.KnownMask>>limbBit)&1 == 1 {
			continue
		}
		p0.SetBit(p0, bit, 0)
		variableBits = append(variableBits, variableBit{bit: bit, lit: factorLowerBitLit(cnf, pLimbs, bit)})
	}

	invP0 := new(big.Int).ModInverse(p0, liftModulus)
	if invP0 == nil {
		return fmt.Errorf("lowlift q=272 p0 is not invertible")
	}
	q0 := new(big.Int).Mul(n, invP0)
	q0.Mod(q0, liftModulus)
	linearBase := new(big.Int).Mul(n, invP0)
	linearBase.Mul(linearBase, invP0)
	linearBase.Neg(linearBase)
	linearBase.Mod(linearBase, liftModulus)

	columns := make([][]int, liftBits)
	trueLit := cnf.TrueLit()
	for bit := 0; bit < liftBits; bit++ {
		if q0.Bit(bit) == 1 {
			columns[bit] = append(columns[bit], trueLit)
		}
	}
	for _, variable := range variableBits {
		if variable.lit == -trueLit {
			continue
		}
		coeff := new(big.Int).Lsh(linearBase, uint(variable.bit))
		coeff.Mod(coeff, liftModulus)
		for bit := 0; bit < liftBits; bit++ {
			if coeff.Bit(bit) == 1 {
				columns[bit] = append(columns[bit], variable.lit)
			}
		}
	}

	for bit := 0; bit < liftBits; bit++ {
		for len(columns[bit]) > 2 {
			nTerms := len(columns[bit])
			a := columns[bit][nTerms-1]
			b := columns[bit][nTerms-2]
			d := columns[bit][nTerms-3]
			columns[bit] = columns[bit][:nTerms-3]
			sum, carry := fullAdderLits(cnf, a, b, d, fmt.Sprintf("lowlift272_%d_%d", bit, len(columns[bit])))
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < liftBits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		if len(columns[bit]) == 2 {
			a := columns[bit][0]
			b := columns[bit][1]
			sum, carry := halfAdderLits(cnf, a, b, fmt.Sprintf("lowlift272_%d", bit))
			columns[bit] = nil
			appendColumnLit(cnf, &columns[bit], sum)
			if bit+1 < liftBits {
				appendColumnLit(cnf, &columns[bit+1], carry)
			}
		}
		sumLit := -trueLit
		if len(columns[bit]) != 0 {
			sumLit = columns[bit][0]
		}
		qLit := factorLowerBitLit(cnf, qLimbs, bit)
		requireEqualLits(cnf, sumLit, qLit)
	}
	return nil
}

func addCarryBits(cnf *CNF, columns [][]int, carry *big.Int, offset int) {
	trueLit := cnf.TrueLit()
	for bit := 0; bit+offset < len(columns); bit++ {
		if carry.Bit(bit) == 1 {
			columns[offset+bit] = append(columns[offset+bit], trueLit)
		}
	}
}

func addOddResidueClauses(cnf *CNF, pLimbs, qLimbs []LimbRef, pHigh, qHigh, n *big.Int, splitBit int, moduli []int) error {
	for _, modulus := range moduli {
		if modulus <= 1 || modulus%2 == 0 || modulus > 127 {
			return fmt.Errorf("odd residue modulus must be odd and in 3..127, got %d", modulus)
		}
		pStates := addResidueAutomaton(cnf, fmt.Sprintf("p_mod_%d", modulus), pLimbs, pHigh, splitBit, pBits, modulus)
		qStates := addResidueAutomaton(cnf, fmt.Sprintf("q_mod_%d", modulus), qLimbs, qHigh, splitBit, pBits, modulus)
		target := int(new(big.Int).Mod(n, big.NewInt(int64(modulus))).Int64())
		for pr := 0; pr < modulus; pr++ {
			for qr := 0; qr < modulus; qr++ {
				if (pr*qr)%modulus == target {
					continue
				}
				addSimplifiedClause(cnf, []int{-pStates[pr], -qStates[qr]})
			}
		}
	}
	return nil
}

func addResidueAutomaton(cnf *CNF, name string, limbs []LimbRef, high *big.Int, splitBit, bits, modulus int) []int {
	trueLit := cnf.TrueLit()
	states := make([]int, modulus)
	for residue := range states {
		states[residue] = -trueLit
	}
	states[0] = trueLit

	for bit := 0; bit < bits; bit++ {
		bitLit := factorBitLit(cnf, limbs, high, splitBit, bit)
		weight := pow2Mod(bit, modulus)
		if bitLit == trueLit {
			next := make([]int, modulus)
			for residue := 0; residue < modulus; residue++ {
				next[(residue+weight)%modulus] = states[residue]
			}
			states = next
			continue
		}
		if bitLit == -trueLit {
			continue
		}
		next := make([]int, modulus)
		for residue := 0; residue < modulus; residue++ {
			next[residue] = cnf.NewVar(fmt.Sprintf("%s_bit_%d_res_%d", name, bit, residue))
		}
		addExactlyOne(cnf, next)
		for residue := 0; residue < modulus; residue++ {
			prev := states[residue]
			if prev == -trueLit {
				continue
			}
			nextZero := next[residue]
			nextOne := next[(residue+weight)%modulus]
			addSimplifiedClause(cnf, []int{-prev, bitLit, nextZero})
			addSimplifiedClause(cnf, []int{-prev, -bitLit, nextOne})
		}
		states = next
	}
	return states
}

func addExactlyOne(cnf *CNF, lits []int) {
	cnf.AddClause(lits...)
	for i := 0; i < len(lits); i++ {
		for j := i + 1; j < len(lits); j++ {
			cnf.AddClause(-lits[i], -lits[j])
		}
	}
}

func pow2Mod(bit, modulus int) int {
	out := 1 % modulus
	for i := 0; i < bit; i++ {
		out = (out * 2) % modulus
	}
	return out
}

func factorBitLit(cnf *CNF, limbs []LimbRef, high *big.Int, splitBit, bit int) int {
	trueLit := cnf.TrueLit()
	if bit >= pBits {
		return -trueLit
	}
	if bit >= splitBit {
		if high.Bit(bit-splitBit) == 1 {
			return trueLit
		}
		return -trueLit
	}
	limbIndex := bit / defaultLimbBit
	limbBit := bit % defaultLimbBit
	limb := limbs[limbIndex]
	if (limb.KnownMask>>limbBit)&1 == 1 {
		if (limb.KnownValue>>limbBit)&1 == 1 {
			return trueLit
		}
		return -trueLit
	}
	return limb.BitVars[limbBit]
}

func productLit(cnf *CNF, a, b int, name string) int {
	trueLit := cnf.TrueLit()
	if a == -trueLit || b == -trueLit {
		return 0
	}
	if a == trueLit {
		return b
	}
	if b == trueLit {
		return a
	}
	out := cnf.NewVar(name)
	addAnd(cnf, out, a, b)
	return out
}

func halfAdderLits(cnf *CNF, a, b int, name string) (int, int) {
	sum := xorLit(cnf, a, b, "hsum_"+name)
	carry := andLit(cnf, a, b, "hcarry_"+name)
	return sum, carry
}

func fullAdderLits(cnf *CNF, a, b, d int, name string) (int, int) {
	tmp := xorLit(cnf, a, b, "xor_tmp_"+name)
	sum := xorLit(cnf, tmp, d, "sum_"+name)
	carry := majority3Lit(cnf, a, b, d, "carry_"+name)
	return sum, carry
}

func xorLit(cnf *CNF, a, b int, name string) int {
	trueLit := cnf.TrueLit()
	if a == -trueLit {
		return b
	}
	if b == -trueLit {
		return a
	}
	if a == trueLit {
		return -b
	}
	if b == trueLit {
		return -a
	}
	if a == b {
		return -trueLit
	}
	if a == -b {
		return trueLit
	}
	out := cnf.NewVar(name)
	addXor(cnf, out, a, b)
	return out
}

func andLit(cnf *CNF, a, b int, name string) int {
	trueLit := cnf.TrueLit()
	if a == -trueLit || b == -trueLit || a == -b {
		return -trueLit
	}
	if a == trueLit {
		return b
	}
	if b == trueLit || a == b {
		return a
	}
	out := cnf.NewVar(name)
	addAnd(cnf, out, a, b)
	return out
}

func orLit(cnf *CNF, a, b int, name string) int {
	trueLit := cnf.TrueLit()
	if a == trueLit || b == trueLit || a == -b {
		return trueLit
	}
	if a == -trueLit {
		return b
	}
	if b == -trueLit || a == b {
		return a
	}
	out := cnf.NewVar(name)
	addOr(cnf, out, a, b)
	return out
}

func majority3Lit(cnf *CNF, a, b, d int, name string) int {
	trueLit := cnf.TrueLit()
	terms := []int{a, b, d}
	nonConst := []int{}
	trueCount := 0
	falseCount := 0
	for _, lit := range terms {
		switch lit {
		case trueLit:
			trueCount++
		case -trueLit:
			falseCount++
		default:
			nonConst = append(nonConst, lit)
		}
	}
	if trueCount >= 2 {
		return trueLit
	}
	if falseCount >= 2 {
		return -trueLit
	}
	if trueCount == 1 {
		if falseCount == 1 {
			return nonConst[0]
		}
		return orLit(cnf, nonConst[0], nonConst[1], "or_"+name)
	}
	if falseCount == 1 {
		return andLit(cnf, nonConst[0], nonConst[1], "and_"+name)
	}

	if a == b || a == d {
		return a
	}
	if b == d {
		return b
	}
	if a == -b {
		return d
	}
	if a == -d {
		return b
	}
	if b == -d {
		return a
	}
	out := cnf.NewVar(name)
	addMajority3(cnf, out, a, b, d)
	return out
}

func addAnd(cnf *CNF, out, a, b int) {
	cnf.AddClause(-out, a)
	cnf.AddClause(-out, b)
	cnf.AddClause(out, -a, -b)
}

func addOr(cnf *CNF, out, a, b int) {
	cnf.AddClause(a, b, -out)
	cnf.AddClause(-a, out)
	cnf.AddClause(-b, out)
}

func addHalfAdder(cnf *CNF, sum, carry, a, b int) {
	addXor(cnf, sum, a, b)
	addAnd(cnf, carry, a, b)
}

func addFullAdder(cnf *CNF, sum, carry, a, b, d int) {
	tmp := cnf.NewVar(fmt.Sprintf("xor_tmp_%d", sum))
	addXor(cnf, tmp, a, b)
	addXor(cnf, sum, tmp, d)
	addMajority3(cnf, carry, a, b, d)
}

func addXor(cnf *CNF, out, a, b int) {
	cnf.AddClause(-a, -b, -out)
	cnf.AddClause(-a, b, out)
	cnf.AddClause(a, -b, out)
	cnf.AddClause(a, b, -out)
}

func addMajority3(cnf *CNF, out, a, b, d int) {
	cnf.AddClause(-a, -b, out)
	cnf.AddClause(-a, -d, out)
	cnf.AddClause(-b, -d, out)
	cnf.AddClause(a, b, -out)
	cnf.AddClause(a, d, -out)
	cnf.AddClause(b, d, -out)
}

func orSmallShifted(value *big.Int, small int, shift int) {
	if small == 0 {
		return
	}
	value.Or(value, new(big.Int).Lsh(big.NewInt(int64(small)), uint(shift)))
}

func printSummary(w io.Writer, model *TailModel) {
	pKnown, pUnknown := countKnown(model.PLimbs)
	qKnown, qUnknown := countKnown(model.QLimbs)
	fmt.Fprintf(w, "T=%d limb_bits=%d lower_limbs=%d tail_limbs=%d\n", model.Input.T, model.Input.LimbBits, model.LowerLimbCount, model.Input.TailLimbs)
	fmt.Fprintf(w, "p_low fixed bits=%d unknown bits=%d\n", pKnown, pUnknown)
	fmt.Fprintf(w, "q_low fixed bits=%d unknown bits=%d\n", qKnown, qUnknown)
	fmt.Fprintf(w, "q prefix bits=%d q prefix start=%d\n", model.QPrefixBits, model.QPrefixStart)
	fmt.Fprintf(w, "p_tail_unknown_bits=%d q_tail_unknown_bits=%d\n", model.PTailUnknownBits, model.QTailUnknownBits)
	if model.QIntervalBound {
		fmt.Fprintf(w, "q interval lower bound enabled: qL_min=0x%s qL_max=0x%s\n", model.QLowMin.Text(16), model.QLowMax.Text(16))
	}
	if len(model.OddResiduePrimes) > 0 {
		fmt.Fprintf(w, "odd residue moduli=%v\n", model.OddResiduePrimes)
	}
	fmt.Fprintf(w, "arithmetic prefix bits=%d skip_known_prefix_bits=%d\n", model.ArithmeticBits, model.SkipKnownPrefixBits)
	if model.TailWindowBits > 0 {
		fmt.Fprintf(w, "tail arithmetic window start=%d bits=%d carry_bits=%d\n", model.TailWindowStart, model.TailWindowBits, model.TailWindowCarryBits)
	}
	if model.ExactTailCarryLimbs > 0 {
		fmt.Fprintf(w, "exact tail carry limbs=%d carry_bits=%d\n", model.ExactTailCarryLimbs, model.ExactCarryBits)
	}
	if model.LowliftQBits > 0 {
		fmt.Fprintf(w, "lowlift q bits=%d\n", model.LowliftQBits)
	}
	fmt.Fprintf(w, "p_high bits=%d q_high bits=%d columns=%d vars=%d clauses=%d\n", model.PHigh.BitLen(), model.QHigh.BitLen(), len(model.Columns), model.CNF.nextVar, len(model.CNF.clauses))
	if model.ArithmeticBits == 0 {
		fmt.Fprintln(w, "note: arithmetic column clauses are not emitted unless arithmetic_bits/--arith-bits is set.")
	}
}

func countKnown(limbs []LimbRef) (known, unknown int) {
	for _, limb := range limbs {
		for bit := 0; bit < defaultLimbBit; bit++ {
			if (limb.KnownMask>>bit)&1 == 1 {
				known++
			} else {
				unknown++
			}
		}
	}
	return known, unknown
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
