"""
LTLFormula class implementing FormulaInterface for Linear Temporal Logic.
"""
from typing import List, Tuple, Optional
from .ltlnode import LTLNode, parse_ltl_string
from .spotutils import (
    areDisjoint,
    areEquivalent,
    generate_accepted_traces,
    generate_traces,
    isNecessaryFor,
    isSufficientFor,
    is_trace_satisfied,
)


class LTLFormula():
    """Formula implementation for Linear Temporal Logic using LTL nodes."""
    
    def __init__(self, ltl_str: str):
        """Initialize with an LTL string."""
        self._ltl_node = parse_ltl_string(ltl_str)
        self.ltl_str = str(ltl_str)

    
    def parse(self, formula_str: str):
        """Parse a formula string into an internal representation."""
        return LTLFormula(formula_str)
    
    def is_equivalent(self, other) -> bool:
        """Check if this formula is equivalent to another."""
        if not isinstance(other, LTLFormula):
            return False
        return areEquivalent(self.ltl_str, other.ltl_str)
    
    def get_intersection(self, other) :
        """Compute the intersection of this formula with another."""
        if not isinstance(other, LTLFormula):
            raise TypeError("Can only compute intersection with another LTLFormula")
        # LTL intersection is conjunction
        intersection_str = f"({self.ltl_str}) & ({other.ltl_str})"
        return LTLFormula(intersection_str)
    
    def get_difference(self, other) :
        """Compute the difference between this formula and another."""
        if not isinstance(other, LTLFormula):
            raise TypeError("Can only compute difference with another LTLFormula")
        # LTL difference: this AND NOT other
        difference_str = f"({self.ltl_str}) & !({other.ltl_str})"
        return LTLFormula(difference_str)
    
    def evaluate_trace(self, trace: str) -> bool:
        """
        Evaluate whether a trace satisfies this LTL formula.
        
        Args:
            trace: A string representation of a trace
            
        Returns:
            True if the trace satisfies the formula, False otherwise
        """
        try:
            return is_trace_satisfied(trace, self.ltl_str)
        except Exception as e:
            return False
    
    def generate_examples(self, max_length: int = 5) -> List[str]:
        """Generate examples of traces that satisfy the formula."""
        try:
            traces = generate_accepted_traces(self.ltl_str, max_traces=max_length)
            return traces if traces else []
        except Exception:
            # If trace generation fails, return empty list
            return []
    
    def analyze_relationship(self, other) -> Tuple[str, Optional[List[str]]]:
        """
        Analyze the relationship between this formula and another.
        Returns a tuple (relationship, examples).
        """
        if not isinstance(other, LTLFormula):
            return ("Incompatible Types", None)
        
        try:
            if areEquivalent(self.ltl_str, other.ltl_str):
                relationship = "Equivalent"
            elif areDisjoint(self.ltl_str, other.ltl_str):
                relationship = "Disjoint"
            elif isSufficientFor(self.ltl_str, other.ltl_str):
                relationship = "Subset"
            elif isNecessaryFor(self.ltl_str, other.ltl_str):
                relationship = "Superset"
            else:
                relationship = "Partial Overlap"
            
            # Generate examples from intersection (conjunction)
            intersection_formula = self.get_intersection(other)
            examples = intersection_formula.generate_examples(max_length=5)
            
            return (relationship, examples)
        except Exception:
            return ("Unknown", None)
    
    def find_distinguishing_example(self, other, max_length: int = 5) -> Optional[Tuple[str, str]]:
        """
        Find a distinguishing example between this formula and another.
        Returns a tuple (example, origin).
        """
        if not isinstance(other, LTLFormula):
            return None
        
        try:
            # Try to find traces accepted by this but not other
            traces_this_only = generate_traces(self.ltl_str, other.ltl_str, max_traces=max_length)
            if traces_this_only:
                return (traces_this_only[0], "formula1_only")
            
            # Try to find traces accepted by other but not this
            traces_other_only = generate_traces(other.ltl_str, self.ltl_str, max_traces=max_length)
            if traces_other_only:
                return (traces_other_only[0], "formula2_only")
            
            return None
        except Exception:
            return None
    
    def __str__(self) -> str:
        """String representation."""
        return self.ltl_str
    
