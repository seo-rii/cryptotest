package main

import (
	"encoding/json"
	"math/big"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestBuildTailModelToyInput(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	input := Input{
		T:         784,
		LimbBits:  defaultLimbBit,
		TailLimbs: 2,
		N:         parseTestUInt(t, "0xf"),
		KnownP:    parseTestUInt(t, "0x1"),
		MaskP:     BigUInt{V: *fullMask},
	}

	model, err := BuildTailModel(input)
	if err != nil {
		t.Fatal(err)
	}
	if model.LowerLimbCount != 49 {
		t.Fatalf("lower limb count = %d, want 49", model.LowerLimbCount)
	}
	if len(model.Columns) != 51 {
		t.Fatalf("columns = %d, want 51", len(model.Columns))
	}
	if model.CNF.nextVar == 0 || len(model.CNF.clauses) == 0 {
		t.Fatalf("expected DIMACS vars and fixed-bit clauses, got vars=%d clauses=%d", model.CNF.nextVar, len(model.CNF.clauses))
	}
}

func TestBuildTailModelAdditionalSplitPoints(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	for _, tc := range []struct {
		t            int
		lowerLimbs   int
		totalColumns int
	}{
		{t: 816, lowerLimbs: 51, totalColumns: 53},
		{t: 832, lowerLimbs: 52, totalColumns: 54},
	} {
		input := Input{
			T:         tc.t,
			LimbBits:  defaultLimbBit,
			TailLimbs: 2,
			N:         parseTestUInt(t, "0xf"),
			KnownP:    parseTestUInt(t, "0x1"),
			MaskP:     BigUInt{V: *fullMask},
		}
		model, err := BuildTailModel(input)
		if err != nil {
			t.Fatalf("BuildTailModel(T=%d): %v", tc.t, err)
		}
		if model.LowerLimbCount != tc.lowerLimbs {
			t.Fatalf("T=%d lower limb count = %d, want %d", tc.t, model.LowerLimbCount, tc.lowerLimbs)
		}
		if len(model.Columns) != tc.totalColumns {
			t.Fatalf("T=%d columns = %d, want %d", tc.t, len(model.Columns), tc.totalColumns)
		}
	}
}

func TestBuildTailModelArithmeticPrefix(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	base := Input{
		T:         784,
		LimbBits:  defaultLimbBit,
		TailLimbs: 2,
		N:         parseTestUInt(t, "0xf"),
		KnownP:    parseTestUInt(t, "0x1"),
		MaskP:     BigUInt{V: *fullMask},
	}
	withoutArithmetic, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	base.ArithmeticBits = 8
	withArithmetic, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withArithmetic.ArithmeticBits != 8 {
		t.Fatalf("arithmetic bits = %d, want 8", withArithmetic.ArithmeticBits)
	}
	if len(withArithmetic.CNF.clauses) <= len(withoutArithmetic.CNF.clauses) {
		t.Fatalf("expected arithmetic clauses to increase clause count: before=%d after=%d", len(withoutArithmetic.CNF.clauses), len(withArithmetic.CNF.clauses))
	}

	base.ArithmeticBits = 800
	base.SkipKnownPrefixLimbs = 1
	withTailArithmetic, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withTailArithmetic.ArithmeticBits != 800 {
		t.Fatalf("tail arithmetic bits = %d, want 800", withTailArithmetic.ArithmeticBits)
	}
	if withTailArithmetic.SkipKnownPrefixBits != 16 {
		t.Fatalf("skip known prefix bits = %d, want 16", withTailArithmetic.SkipKnownPrefixBits)
	}

	base.SkipKnownPrefixLimbs = 0
	base.SkipKnownPrefixBits = 20
	withBitSkip, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withBitSkip.SkipKnownPrefixBits != 20 {
		t.Fatalf("bit skip known prefix bits = %d, want 20", withBitSkip.SkipKnownPrefixBits)
	}
	for idx, clause := range withBitSkip.CNF.clauses {
		if len(clause) == 0 {
			t.Fatalf("skip-known-prefix model emitted empty clause at index %d", idx)
		}
	}

	base.ArithmeticBits = pBits + 1
	base.SkipKnownPrefixBits = 0
	base.SkipKnownPrefixLimbs = 1
	extendedProductPrefix, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if extendedProductPrefix.ArithmeticBits != pBits+1 {
		t.Fatalf("extended arithmetic bits = %d, want %d", extendedProductPrefix.ArithmeticBits, pBits+1)
	}

	base.ArithmeticBits = productBits + 1
	if _, err := BuildTailModel(base); err == nil {
		t.Fatalf("expected arithmetic_bits beyond product width to fail")
	}
}

func TestBuildTailModelTailWindow(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	base := Input{
		T:         784,
		LimbBits:  defaultLimbBit,
		TailLimbs: 2,
		N:         parseTestUInt(t, "0xf"),
		KnownP:    parseTestUInt(t, "0x1"),
		MaskP:     BigUInt{V: *fullMask},
	}
	withoutWindow, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	base.TailWindowStart = 0
	base.TailWindowBits = 8
	base.TailWindowCarryBits = 0
	withWindow, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withWindow.TailWindowStart != 784 {
		t.Fatalf("zero tail window start should default to T, got %d", withWindow.TailWindowStart)
	}
	if withWindow.TailWindowBits != 8 || withWindow.TailWindowCarryBits != 12 {
		t.Fatalf("bad tail window metadata: bits=%d carry=%d", withWindow.TailWindowBits, withWindow.TailWindowCarryBits)
	}
	if len(withWindow.CNF.clauses) <= len(withoutWindow.CNF.clauses) {
		t.Fatalf("expected tail window clauses to increase clause count: before=%d after=%d", len(withoutWindow.CNF.clauses), len(withWindow.CNF.clauses))
	}

	base.TailWindowStart = productBits
	if _, err := BuildTailModel(base); err == nil {
		t.Fatalf("expected out-of-range tail window start to fail")
	}
}

func TestBuildTailModelExactTailCarryColumns(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	base := Input{
		T:         784,
		LimbBits:  defaultLimbBit,
		TailLimbs: 2,
		N:         parseTestUInt(t, "0xf"),
		KnownP:    parseTestUInt(t, "0x1"),
		MaskP:     BigUInt{V: *fullMask},
	}
	withoutExact, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	base.ExactTailCarryLimbs = 1
	base.ExactCarryBits = 24
	withExact, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withExact.ExactTailCarryLimbs != 1 || withExact.ExactCarryBits != 24 {
		t.Fatalf("bad exact carry metadata: limbs=%d carry_bits=%d", withExact.ExactTailCarryLimbs, withExact.ExactCarryBits)
	}
	if len(withExact.CNF.clauses) <= len(withoutExact.CNF.clauses) {
		t.Fatalf("expected exact carry clauses to increase clause count: before=%d after=%d", len(withoutExact.CNF.clauses), len(withExact.CNF.clauses))
	}
	base.SkipKnownPrefixLimbs = 1
	withSkip, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withSkip.SkipKnownPrefixBits != 16 {
		t.Fatalf("bad exact carry skip bits: %d", withSkip.SkipKnownPrefixBits)
	}
	if len(withSkip.CNF.clauses) >= len(withExact.CNF.clauses) {
		t.Fatalf("expected exact carry skip to reduce clause count: unskipped=%d skipped=%d", len(withExact.CNF.clauses), len(withSkip.CNF.clauses))
	}
	base.SkipKnownPrefixLimbs = 0
	base.ExactTailCarryLimbs = 3
	if _, err := BuildTailModel(base); err == nil {
		t.Fatalf("expected exact tail carry limbs beyond tail_limbs to fail")
	}
}

func TestAddExactCarryColumnClausesToyProduct(t *testing.T) {
	var cnf CNF
	pValue := uint64(0x1235)
	qValue := uint64(0x4567)
	pKnown := new(big.Int).SetUint64(pValue)
	qKnown := big.NewInt(0)
	pMask := big.NewInt(0xffff)
	qMask := big.NewInt(0)
	pLimbs := buildLimbs(&cnf, "p", pKnown, pMask, 1)
	qLimbs := buildLimbs(&cnf, "q", qKnown, qMask, 1)
	carryMarkers := make([]int, 2)

	n := new(big.Int).SetUint64(pValue * qValue)
	columns := buildColumns(Input{LimbBits: defaultLimbBit}, pLimbs, qLimbs, n, big.NewInt(0), big.NewInt(0), carryMarkers)
	if err := addExactCarryColumnClauses(&cnf, columns, 16, 0, big.NewInt(0)); err != nil {
		t.Fatal(err)
	}
	if len(cnf.clauses) == 0 {
		t.Fatalf("expected exact carry-column clauses")
	}

	units := []int{}
	for bit := 0; bit < 16; bit++ {
		qLit := factorLowerBitLit(&cnf, qLimbs, bit)
		if (qValue>>bit)&1 == 0 {
			qLit = -qLit
		}
		units = append(units, qLit)
	}
	if unitPropagationConflicts(cnf.clauses, units) {
		t.Fatalf("correct toy product assignment conflicts with exact carry-column CNF")
	}

	badUnits := []int{}
	badQValue := qValue ^ 1
	for bit := 0; bit < 16; bit++ {
		qLit := factorLowerBitLit(&cnf, qLimbs, bit)
		if (badQValue>>bit)&1 == 0 {
			qLit = -qLit
		}
		badUnits = append(badUnits, qLit)
	}
	if !unitPropagationConflicts(cnf.clauses, badUnits) {
		t.Fatalf("wrong toy product assignment did not conflict with exact carry-column CNF")
	}
}

func TestAddLowliftQ265Clauses(t *testing.T) {
	var cnf CNF
	limbCount := (265 + defaultLimbBit - 1) / defaultLimbBit
	pKnown := parseTestUInt(t, "0x1")
	pMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(limbCount*defaultLimbBit)), big.NewInt(1))
	x1Mask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 39), big.NewInt(1))
	x1Mask.Lsh(x1Mask, 210)
	pMask.AndNot(pMask, x1Mask)

	qKnown := new(big.Int)
	qMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(limbCount*defaultLimbBit)), big.NewInt(1))
	qMidMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 55), big.NewInt(1))
	qMidMask.Lsh(qMidMask, 210)
	qMask.AndNot(qMask, qMidMask)

	pLimbs := buildLimbs(&cnf, "p", &pKnown.V, pMask, limbCount)
	qLimbs := buildLimbs(&cnf, "q", qKnown, qMask, limbCount)
	before := len(cnf.clauses)
	n := parseTestUInt(t, "0xf")
	if err := addLowliftQ265Clauses(&cnf, pLimbs, qLimbs, &n.V, &pKnown.V); err != nil {
		t.Fatal(err)
	}
	if len(cnf.clauses) <= before {
		t.Fatalf("expected lowlift q clauses to be emitted: before=%d after=%d", before, len(cnf.clauses))
	}
	for idx, clause := range cnf.clauses {
		if len(clause) == 0 {
			t.Fatalf("lowlift q model emitted empty clause at index %d", idx)
		}
	}

	for _, x1 := range []uint64{0, 0x7fffffffff} {
		expected := expectedQMid265(t, &n.V, &pKnown.V, x1)
		if lowliftAssignmentConflicts(&cnf, pLimbs, qLimbs, x1, expected) {
			t.Fatalf("x1=%#x expected q-mid %#x conflicts with lowlift CNF", x1, expected)
		}
		if !lowliftAssignmentConflicts(&cnf, pLimbs, qLimbs, x1, expected^1) {
			t.Fatalf("x1=%#x wrong q-mid %#x did not conflict with lowlift CNF", x1, expected^1)
		}
	}
}

func TestAddLowliftQ272Clauses(t *testing.T) {
	var cnf CNF
	limbCount := (272 + defaultLimbBit - 1) / defaultLimbBit
	pKnown := parseTestUInt(t, "0x1")
	pMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(limbCount*defaultLimbBit)), big.NewInt(1))
	for _, r := range []struct {
		start int
		width int
	}{
		{start: 210, width: 39},
		{start: 265, width: 7},
	} {
		mask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), uint(r.width)), big.NewInt(1))
		mask.Lsh(mask, uint(r.start))
		pMask.AndNot(pMask, mask)
	}

	qKnown := new(big.Int)
	qMask := new(big.Int)

	pLimbs := buildLimbs(&cnf, "p", &pKnown.V, pMask, limbCount)
	qLimbs := buildLimbs(&cnf, "q", qKnown, qMask, limbCount)
	before := len(cnf.clauses)
	n := parseTestUInt(t, "0xf")
	if err := addLowliftQ272Clauses(&cnf, pLimbs, qLimbs, &n.V, &pKnown.V); err != nil {
		t.Fatal(err)
	}
	if len(cnf.clauses) <= before {
		t.Fatalf("expected lowlift q272 clauses to be emitted: before=%d after=%d", before, len(cnf.clauses))
	}
	for idx, clause := range cnf.clauses {
		if len(clause) == 0 {
			t.Fatalf("lowlift q272 model emitted empty clause at index %d", idx)
		}
	}

	x1 := uint64(0x123456789a)
	x2 := uint64(0x55)
	expected := expectedQLowLift(t, &n.V, &pKnown.V, x1, x2, 272)
	if lowlift272AssignmentConflicts(&cnf, pLimbs, qLimbs, x1, x2, expected) {
		t.Fatalf("x1=%#x x2=%#x expected q-low conflicts with lowlift q272 CNF", x1, x2)
	}
	wrong := new(big.Int).Xor(expected, big.NewInt(1))
	if !lowlift272AssignmentConflicts(&cnf, pLimbs, qLimbs, x1, x2, wrong) {
		t.Fatalf("x1=%#x x2=%#x wrong q-low did not conflict with lowlift q272 CNF", x1, x2)
	}
}

func expectedQMid265(t *testing.T, n, knownP *big.Int, x1 uint64) uint64 {
	t.Helper()
	const (
		x1Start  = 210
		qMidBits = 55
		liftBits = 265
	)
	modulus := new(big.Int).Lsh(big.NewInt(1), liftBits)
	pLow := new(big.Int).And(knownP, new(big.Int).Sub(modulus, big.NewInt(1)))
	pLow.Add(pLow, new(big.Int).Lsh(new(big.Int).SetUint64(x1), x1Start))
	pLow.Mod(pLow, modulus)
	inv := new(big.Int).ModInverse(pLow, modulus)
	if inv == nil {
		t.Fatalf("p low is not invertible for x1=%#x", x1)
	}
	qLow := new(big.Int).Mul(n, inv)
	qLow.Mod(qLow, modulus)
	qLow.Rsh(qLow, x1Start)
	qLow.And(qLow, new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), qMidBits), big.NewInt(1)))
	return qLow.Uint64()
}

func expectedQLowLift(t *testing.T, n, knownP *big.Int, x1, x2 uint64, liftBits int) *big.Int {
	t.Helper()
	modulus := new(big.Int).Lsh(big.NewInt(1), uint(liftBits))
	pLow := new(big.Int).And(knownP, new(big.Int).Sub(modulus, big.NewInt(1)))
	pLow.Add(pLow, new(big.Int).Lsh(new(big.Int).SetUint64(x1), 210))
	pLow.Add(pLow, new(big.Int).Lsh(new(big.Int).SetUint64(x2), 265))
	pLow.Mod(pLow, modulus)
	inv := new(big.Int).ModInverse(pLow, modulus)
	if inv == nil {
		t.Fatalf("p low is not invertible for x1=%#x x2=%#x", x1, x2)
	}
	qLow := new(big.Int).Mul(n, inv)
	qLow.Mod(qLow, modulus)
	return qLow
}

func lowliftAssignmentConflicts(cnf *CNF, pLimbs, qLimbs []LimbRef, x1 uint64, qMid uint64) bool {
	units := []int{}
	for off := 0; off < 39; off++ {
		lit := factorLowerBitLit(cnf, pLimbs, 210+off)
		if (x1>>off)&1 == 0 {
			lit = -lit
		}
		units = append(units, lit)
	}
	for off := 0; off < 55; off++ {
		lit := factorLowerBitLit(cnf, qLimbs, 210+off)
		if (qMid>>off)&1 == 0 {
			lit = -lit
		}
		units = append(units, lit)
	}
	return unitPropagationConflicts(cnf.clauses, units)
}

func lowlift272AssignmentConflicts(cnf *CNF, pLimbs, qLimbs []LimbRef, x1, x2 uint64, qLow *big.Int) bool {
	units := []int{}
	for off := 0; off < 39; off++ {
		lit := factorLowerBitLit(cnf, pLimbs, 210+off)
		if (x1>>off)&1 == 0 {
			lit = -lit
		}
		units = append(units, lit)
	}
	for off := 0; off < 7; off++ {
		lit := factorLowerBitLit(cnf, pLimbs, 265+off)
		if (x2>>off)&1 == 0 {
			lit = -lit
		}
		units = append(units, lit)
	}
	for off := 0; off < 272; off++ {
		lit := factorLowerBitLit(cnf, qLimbs, off)
		if qLow.Bit(off) == 0 {
			lit = -lit
		}
		units = append(units, lit)
	}
	return unitPropagationConflicts(cnf.clauses, units)
}

func unitPropagationConflicts(clauses [][]int, units []int) bool {
	assignments := map[int]bool{}
	queue := append([]int{}, units...)
	for len(queue) > 0 {
		lit := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		variable := lit
		value := true
		if variable < 0 {
			variable = -variable
			value = false
		}
		if current, ok := assignments[variable]; ok {
			if current != value {
				return true
			}
			continue
		}
		assignments[variable] = value

		for _, clause := range clauses {
			satisfied := false
			unassigned := 0
			lastUnassigned := 0
			for _, clauseLit := range clause {
				clauseVariable := clauseLit
				clauseValue := true
				if clauseVariable < 0 {
					clauseVariable = -clauseVariable
					clauseValue = false
				}
				if assigned, ok := assignments[clauseVariable]; ok {
					if assigned == clauseValue {
						satisfied = true
						break
					}
				} else {
					unassigned++
					lastUnassigned = clauseLit
				}
			}
			if satisfied {
				continue
			}
			if unassigned == 0 {
				return true
			}
			if unassigned == 1 {
				queue = append(queue, lastUnassigned)
			}
		}
	}
	return false
}

func TestBuildTailModelQIntervalBound(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	base := Input{
		T:         784,
		LimbBits:  defaultLimbBit,
		TailLimbs: 2,
		N:         parseTestUInt(t, "0xf"),
		KnownP:    parseTestUInt(t, "0x1"),
		MaskP:     BigUInt{V: *fullMask},
	}
	withoutBound, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	base.QIntervalBound = true
	withBound, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if !withBound.QIntervalBound {
		t.Fatalf("expected q interval bound to be enabled")
	}
	if withBound.QLowMin.Cmp(big.NewInt(15)) != 0 || withBound.QLowMax.Cmp(big.NewInt(15)) != 0 {
		t.Fatalf("bad q lower interval: min=%s max=%s", withBound.QLowMin.Text(16), withBound.QLowMax.Text(16))
	}
	if len(withBound.CNF.clauses) <= len(withoutBound.CNF.clauses) {
		t.Fatalf("expected q interval clauses to increase clause count: before=%d after=%d", len(withBound.CNF.clauses), len(withoutBound.CNF.clauses))
	}
}

func TestBuildTailModelOddResiduePrimes(t *testing.T) {
	fullMask := new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), pBits), big.NewInt(1))
	base := Input{
		T:         784,
		LimbBits:  defaultLimbBit,
		TailLimbs: 2,
		N:         parseTestUInt(t, "0xf"),
		KnownP:    parseTestUInt(t, "0x1"),
		MaskP:     BigUInt{V: *fullMask},
	}
	withoutResidues, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	base.OddResiduePrimes = []int{3, 5}
	withResidues, err := BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if len(withResidues.OddResiduePrimes) != 2 {
		t.Fatalf("odd residue primes = %+v, want two moduli", withResidues.OddResiduePrimes)
	}
	if withResidues.CNF.nextVar > withoutResidues.CNF.nextVar+1 {
		t.Fatalf("known odd residue automata should not add variables: before=%d after=%d", withoutResidues.CNF.nextVar, withResidues.CNF.nextVar)
	}
	if len(withResidues.CNF.clauses) > len(withoutResidues.CNF.clauses)+1 {
		t.Fatalf("known odd residue automata should simplify away clauses: before=%d after=%d", len(withoutResidues.CNF.clauses), len(withResidues.CNF.clauses))
	}

	partialMask := new(big.Int).Set(fullMask)
	partialMask.SetBit(partialMask, 210, 0)
	base.MaskP = BigUInt{V: *partialMask}
	base.OddResiduePrimes = nil
	withoutResidues, err = BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	base.OddResiduePrimes = []int{3, 5}
	withResidues, err = BuildTailModel(base)
	if err != nil {
		t.Fatal(err)
	}
	if withResidues.CNF.nextVar <= withoutResidues.CNF.nextVar {
		t.Fatalf("unknown odd residue automata should add variables: before=%d after=%d", withoutResidues.CNF.nextVar, withResidues.CNF.nextVar)
	}
	if len(withResidues.CNF.clauses) <= len(withoutResidues.CNF.clauses) {
		t.Fatalf("unknown odd residue automata should add clauses: before=%d after=%d", len(withoutResidues.CNF.clauses), len(withResidues.CNF.clauses))
	}
}

func TestLoadInputParsesPlanArgv(t *testing.T) {
	path := filepath.Join(t.TempDir(), "input.json")
	payload := map[string]any{
		"n":       "0xf",
		"known_p": "0x1",
		"mask_p":  "0x1",
		"argv": []string{
			"python3", "try_hensel_tail_cp_sat.py",
			"--T", "800",
			"--tail-limbs", "3",
			"--arith-bits", "32",
			"--skip-known-prefix-bits", "20",
			"--tail-window-start", "800",
			"--tail-window-bits", "32",
			"--tail-window-carry-bits", "11",
			"--exact-tail-carry-limbs", "2",
			"--exact-carry-bits", "28",
			"--q-interval-bound",
			"--odd-residue-prime", "3",
			"--odd-residue-primes", "5,7",
			"--branch-low", "0xa",
			"--fix-p-range", "210:4:0x5",
			"--decision-q-range", "300:16",
		},
	}
	data, err := json.Marshal(payload)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}

	input, err := loadInput(path)
	if err != nil {
		t.Fatal(err)
	}
	if input.T != 800 || input.TailLimbs != 3 || input.BranchLow != 0xa {
		t.Fatalf("bad argv parse: T=%d tail=%d branch_low=%x", input.T, input.TailLimbs, input.BranchLow)
	}
	if input.ArithmeticBits != 32 {
		t.Fatalf("bad arithmetic bits parse: %d", input.ArithmeticBits)
	}
	if input.SkipKnownPrefixBits != 20 {
		t.Fatalf("bad skip-known-prefix-bits parse: %d", input.SkipKnownPrefixBits)
	}
	if input.TailWindowStart != 800 || input.TailWindowBits != 32 || input.TailWindowCarryBits != 11 {
		t.Fatalf("bad tail window parse: start=%d bits=%d carry=%d", input.TailWindowStart, input.TailWindowBits, input.TailWindowCarryBits)
	}
	if input.ExactTailCarryLimbs != 2 || input.ExactCarryBits != 28 {
		t.Fatalf("bad exact carry parse: limbs=%d bits=%d", input.ExactTailCarryLimbs, input.ExactCarryBits)
	}
	if !input.QIntervalBound {
		t.Fatalf("expected q interval bound flag")
	}
	if got, want := input.OddResiduePrimes, []int{3, 5, 7}; len(got) != len(want) || got[0] != want[0] || got[1] != want[1] || got[2] != want[2] {
		t.Fatalf("bad odd residue parse: %+v", input.OddResiduePrimes)
	}
	if len(input.FixedP) != 1 || input.FixedP[0].Start != 210 || input.FixedP[0].Value.V.Uint64() != 5 {
		t.Fatalf("bad fixed p parse: %+v", input.FixedP)
	}
	if len(input.DecisionQ) != 1 || input.DecisionQ[0].Start != 300 || input.DecisionQ[0].Width != 16 {
		t.Fatalf("bad decision q parse: %+v", input.DecisionQ)
	}
}

func TestWriteDIMACSCanOmitComments(t *testing.T) {
	var cnf CNF
	cnf.AddClause(cnf.NewVar("x"))
	withComments := new(strings.Builder)
	if err := cnf.WriteDIMACS(withComments, true); err != nil {
		t.Fatal(err)
	}
	withoutComments := new(strings.Builder)
	if err := cnf.WriteDIMACS(withoutComments, false); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(withComments.String(), "c var") {
		t.Fatalf("expected variable comment in DIMACS with comments: %q", withComments.String())
	}
	if strings.Contains(withoutComments.String(), "c var") {
		t.Fatalf("unexpected variable comment in DIMACS without comments: %q", withoutComments.String())
	}
}

func TestWriteVariableMapJSONFiltersFactorBits(t *testing.T) {
	var cnf CNF
	p := cnf.NewVar("p_265")
	q := cnf.NewVar("q_17")
	_ = cnf.NewVar("mul_1_2")

	out := new(strings.Builder)
	if err := cnf.WriteVariableMapJSON(out, []string{"p_", "q_"}); err != nil {
		t.Fatal(err)
	}

	var decoded map[string]int
	if err := json.Unmarshal([]byte(out.String()), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["p_265"] != p || decoded["q_17"] != q {
		t.Fatalf("bad p/q var map: %+v", decoded)
	}
	if _, ok := decoded["mul_1_2"]; ok {
		t.Fatalf("unexpected multiplier var in factor bit map: %+v", decoded)
	}
}

func TestAdderLiteralHelpersSimplifyConstants(t *testing.T) {
	var cnf CNF
	trueLit := cnf.TrueLit()
	beforeVars := cnf.nextVar
	beforeClauses := len(cnf.clauses)

	sum, carry := fullAdderLits(&cnf, trueLit, -trueLit, trueLit, "const_full")
	if sum != -trueLit || carry != trueLit {
		t.Fatalf("bad constant full-adder result: sum=%d carry=%d true=%d", sum, carry, trueLit)
	}
	halfSum, halfCarry := halfAdderLits(&cnf, -trueLit, -trueLit, "const_half")
	if halfSum != -trueLit || halfCarry != -trueLit {
		t.Fatalf("bad constant half-adder result: sum=%d carry=%d true=%d", halfSum, halfCarry, trueLit)
	}
	if cnf.nextVar != beforeVars || len(cnf.clauses) != beforeClauses {
		t.Fatalf(
			"constant adders should not allocate clauses/vars: vars %d -> %d clauses %d -> %d",
			beforeVars,
			cnf.nextVar,
			beforeClauses,
			len(cnf.clauses),
		)
	}
}

func parseTestUInt(t *testing.T, text string) BigUInt {
	t.Helper()
	var value BigUInt
	if err := value.UnmarshalJSON([]byte(`"` + text + `"`)); err != nil {
		t.Fatal(err)
	}
	return value
}
