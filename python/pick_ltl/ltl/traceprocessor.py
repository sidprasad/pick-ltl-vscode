import random
import re

from . import ltlnode

## TODO: MAY NOT WANT MERMAID SINCE ITS FINNICKY.


## Narrow formula
def choosePathFromWord(word):
    asNode = ltlnode.parse_ltl_string(word)
    modifiedNode = removeORs(asNode)
    x = str(modifiedNode)
    return x

# Now go down the word, if there is an OR choose one of left or right at random
def removeORs(node):
    

    ## SP: Right now this choice is random.
    ## BUT we may want to make it deterministic if the SAME person
    ## does the same thing.

    ## [FLAGGING RANDOMNESS]
    if isinstance(node, ltlnode.OrNode):
        # Choose one of node.left or node.right
        if random.choice([True, False]):
            return removeORs(node.left)
        else:
            return removeORs(node.right)
    elif isinstance(node, ltlnode.BinaryOperatorNode):
        node.left = removeORs(node.left)
        node.right = removeORs(node.right)
    elif isinstance(node, ltlnode.UnaryOperatorNode):
        node.operand = removeORs(node.operand)
    
    return node



class NodeRepr:

    VAR_SEPARATOR = '&'

    def __init__(self, vars):
        self.vars = vars.strip()

        if (not self.vars.startswith('cycle')):
            try:
                vs = choosePathFromWord(self.vars)
                self.vars = vs
            except Exception as e:
                print(f"Error parsing: {self.vars}")
                print(e)

        self.vars = self.vars.replace('&', self.VAR_SEPARATOR)
        self.id = ''.join(random.choices('abcfghijklmopqrstuvwxyzABCFGHIJKLMOPQRSTUVWXYZ', k=6))


    def __mermaid_str__(self):
        asStr = self.__str__()

        # And now, we replace the VAR_SEPARATOR with a space
        asStr = asStr.replace(self.VAR_SEPARATOR, '\u2003')
        # I also want to replace '! ' with '!'
        asStr = asStr.replace('! ', '!')
        #and replace '!' with '¬'
        asStr = asStr.replace('!', '¬')

        return f'{self.id}["{asStr}"]'
    
    def __str__(self):
        asStr = self.vars
        if '{' in asStr or '}' in asStr:
            asStr = asStr.replace('{', '').replace('}', '')
        # Now remove all the parens
        asStr = asStr.replace('(', '').replace(')', '')
        return asStr

    def __add_missing_literals__(self, missing_literals):
        s = self.vars
        for literal in missing_literals:
            x = literal if random.random() < 0.5 else f'!{literal}'
            if s == "":
                s = x
            else:
                s = f'({s}) {NodeRepr.VAR_SEPARATOR} {x}'
        self.vars = s


    def expand(self, literals):

        TAUTOLOGY = r'\b1\b'
        UNSAT = r'\b0\b'

        if self.vars == "0":
            self.vars = "unsat"
            return
        
        if self.vars == "1":
            self.vars = ""
        
        s = self.vars
        vars_words = re.findall(r'\b[a-z0-9]+\b', s)
        missing_literals = [literal for literal in literals if literal not in vars_words]
        self.__add_missing_literals__(missing_literals)



def spotTraceToNodeReprs(sr):
    sr = sr.strip()
    if sr == "":
        return []

    prefix_split = sr.split('cycle', 1)
    prefix_parts = [x for x in prefix_split[0].strip().split(';') if x.strip() != ""]
    states = [NodeRepr(part) for part in prefix_parts]

    cycle_states = []
    ## Would be weird to not have a cycle, but we allow for it.
    if len(prefix_split) > 1:
        cycle = prefix_split[1]
        # Cycle candidate has no string 'cycle' in it here.
        cycled_content = getCycleContent(cycle)
        cycle_states = [NodeRepr(part) for part in cycled_content.split(';') if part.strip() != ""]
        # NB: the cycle states are exactly the period of the lasso — `cycle{A;B}`
        # repeats A,B,A,B,... Do NOT append cycle_states[0] here: that lengthens
        # the period (A,B -> A,B,A) and changes which traces the lasso denotes,
        # so a round-trip through expandSpotTrace would no longer satisfy the
        # formula it was generated from. The closing edge back to the first
        # cycle state is a *rendering* concern; mermaidFromSpotTrace adds it.

    return {
        "prefix_states": states,
        "cycle_states": cycle_states
    }

def nodeReprListsToSpotTrace(prefix_states, cycle_states) -> str:
    prefix_string = ';'.join([str(state) for state in prefix_states])
    cycle_string = "cycle{" +  ';'.join([str(state) for state in cycle_states]) + "}"

    if prefix_string == "":
        return cycle_string
    if cycle_string == "":
        return prefix_string

    return prefix_string + ";" + cycle_string



def expandSpotTrace(sr, literals) -> str:




    nodeRepr = spotTraceToNodeReprs(sr)
    prefix_states = nodeRepr["prefix_states"]
    cycle_states = nodeRepr["cycle_states"]

    if len(literals) > 0:

        for state in prefix_states:
            state.expand(literals)
        for state in cycle_states:
            state.expand(literals)    
    
    sr = nodeReprListsToSpotTrace(prefix_states, cycle_states)
    return sr

def getCycleContent(string):
    match = re.match(r'.*\{([^}]*)\}', string)
    return match.group(1) if match else ""

def mermaidFromSpotTrace(sr):
    nodeRepr = spotTraceToNodeReprs(sr)
    prefix_states = nodeRepr["prefix_states"]
    cycle_states = list(nodeRepr["cycle_states"])
    # Close the lasso visually: draw the edge from the last cycle state back to
    # the first. This is rendering-only; the canonical trace (expandSpotTrace)
    # must not carry this duplicate or its period would change.
    if cycle_states:
        cycle_states = cycle_states + [cycle_states[0]]
    states = prefix_states + cycle_states

    edges = []
    for i in range(1, len(states)):
        current = states[i - 1]
        next = states[i]
        edges.append((current, next))

    return edges

def mermaidGraphFromEdgesList(edges):
    diagramText = 'flowchart LR;'

    for edge in edges:
        diagramText += f'{edge[0].__mermaid_str__()}-->{edge[1].__mermaid_str__()};'

    return diagramText


def genMermaidGraphFromSpotTrace(sr):
    edges = mermaidFromSpotTrace(sr)
    return mermaidGraphFromEdgesList(edges)


def expand_single_trace_to_mermaid(sr, literals):
    sr = expandSpotTrace(sr, literals)
    return genMermaidGraphFromSpotTrace(sr)



def getFormulaLiterals(ltlFormula):
    n = ltlnode.parse_ltl_string(ltlFormula)

    literals = set()

    def getLiterals(n):
        t_n = type(n)
        t_n_str = n.type
        if t_n is ltlnode.LiteralNode or t_n_str == 'Literal':
            literals.add(n.value)
        elif t_n is ltlnode.UnaryOperatorNode or t_n_str == 'UnaryOperator':
            getLiterals(n.operand)
        elif t_n is ltlnode.BinaryOperatorNode or n.type == 'BinaryOperator':
            getLiterals(n.left)
            getLiterals(n.right)
        else:
            raise TypeError(f"Unknown node type: {type(n)}")
    
    getLiterals(n)
    return literals
