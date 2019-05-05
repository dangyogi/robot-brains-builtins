# symtable.py

from collections import OrderedDict
from copy import deepcopy
from math import isclose
from itertools import tee, zip_longest, chain

import scanner


Last_parameter_obj = None


def pairwise(iterable, fillvalue=None):
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = tee(iterable)
    next(b, None)
    return zip_longest(a, b, fillvalue=fillvalue)


def aeq(x, y):
    return isclose(x, y, rel_tol=0, abs_tol=1e-6)


def last_parameter_obj():
    return Last_parameter_obj


def current_namespace():
    return scanner.Namespaces[-1]


def top_namespace():
    return scanner.Namespaces[0]


class Hook_base:
    r'''Implements hook capability.

    - Only allows one fn to be registered per cls, hook_name.
    - Only calls the first fn found (in __mro__ order) when the hook is
      triggered.
    '''
    hooks = {}    # {(cls, hook_name): fn}

    @classmethod
    def add_hook(cls, hook_name, fn):
        assert (cls, hook_name) not in Hook_base.hooks, \
               f"More than one {hook_name!r} hook on {cls.__name__}"
        Hook_base.hooks[cls, hook_name] = fn
    
    def run_hook(self, hook_name, *args, **kws):
        r'''Passes self to the hook fn, in addition to *args and **kws.

        Returns result of hook fn call -- None if no hook fn.
        '''
        for c in self.__class__.__mro__:
            fn = Hook_base.hooks.get((c, hook_name))
            if fn is not None:
                return fn(self, *args, **kws)


class Symtable(Hook_base):
    r'''Root of all symtable classes.

    Defines dump, prepare and prepare_step.
    '''
    prepared = False

    def dump(self, f, indent=0):
        print(f"{indent_str(indent)}{self.__class__.__name__}", end='', file=f)
        self.dump_details(f)
        print(file=f)
        self.dump_contents(f, indent + 2)

    def dump_details(self, f):
        pass

    def dump_contents(self, f, indent):
        pass

    def prepare(self, module):
        r'''Called once per instance.
        '''
        if not self.prepared:
            self.prepared = True
            self.do_prepare(module)
            self.run_hook("prepare", module)

    def do_prepare(self, module):
        r'''Override this in the subclasses.
        '''
        pass


class Entity(Symtable):
    r'''Named entities within a namespace.
    '''
    def __init__(self, ident):
        self.name = ident
        self.set_in_namespace()

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name.value}>"

    def set_in_namespace(self):
        self.parent_namespace = current_namespace()
        self.parent_namespace.set(self.name, self)

    def dump_details(self, f):
        super().dump_details(f)
        print(f" {self.name.value}", end='', file=f)


class Variable(Entity):
    r'''self.set_bit is the bit number in module.vars_set.  Set in prepare.
    '''
    explicit_typedef = False
    dimensions = ()
    immediate = False
    constant = False

    def __init__(self, ident, **kws):
        Entity.__init__(self, ident)
        self.lexpos = ident.lexpos
        self.lineno = ident.lineno
        self.filename = ident.filename
        self.type = Builtin_type(ident.type)
        for k, v in kws.items():
            setattr(self, k, v)
        self.parameter_list = []        # list of parameters using this Variable

    def dump_details(self, f):
        super().dump_details(f)
        print(f" type={self.type}", end='', file=f)

    def do_prepare(self, module):
        super().do_prepare(module)
        if not self.dimensions:
            self.set_bit = module.next_set_bit
            module.next_set_bit += 1
        self.type.prepare(module)

    def set_module(self, module):
        self.immediate = True
        assert module.immediate
        self.value = module.value

    def get_step(self):
        return self

    def is_numeric(self):
        return self.type.is_numeric()

    def is_integer(self):
        return self.type.is_integer()

    def is_float(self):
        return self.type.is_float()

    def is_string(self):
        return self.type.is_string()

    def is_boolean(self):
        return self.type.is_boolean()

    def is_module(self):
        return self.type.is_module()


class Required_parameter(Symtable):
    r'''
    self.param_pos_number assigned in Param_block.add_parameter.
    '''
    def __init__(self, ident):
        self.name = ident
        self.variable = current_namespace().make_variable(ident)
        self.variable.parameter_list.append(self)
        Last_parameter_obj.pos_parameter(self)

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name.value}>"

    def dump_details(self, f):
        super().dump_details(f)
        print(' ', self.name.value, sep='', end='', file=f)
        if hasattr(self, 'param_pos_number'):
            print(f" param_pos_number={self.param_pos_number}", end='', file=f)

    def do_prepare(self, module):
        super().do_prepare(module)
        self.type = self.variable.type


class Optional_parameter(Required_parameter):
    r'''
    self.passed_bit assigned in Param_block.assign_passed_bits.  This is the
    bit number, not the bit mask.

    self.passed is set to True/False at compile time for module parameters.
    '''
    pass


class Use(Entity):
    def __init__(self, ident, module_name, pos_arguments, kw_arguments):
        Entity.__init__(self, ident)
        self.module_name = module_name
        self.pos_arguments = pos_arguments  # (primary, ...)

        # ((KEYWORD_TOKEN, (primary, ...)), ...)
        self.kw_arguments = kw_arguments

    def __repr__(self):
        return f"<Use {self.name.value} {self.module_name.value}>"

    def copy_module(self):
        self.module = \
          deepcopy(Opmode_module.modules_seen[self.module_name.value])
        self.module.link_uses()

    def dump_details(self, f):
        super().dump_details(f)
        print(f" module_name={self.module_name}", end='', file=f)

    def prepare_used_module(self, module):
        r'''
        Broken out so that builtins and opmode get prepared before used modules
        so that their Entities are initialized before being referenced in used
        modules.
        '''
        #print("Use.prepare_used_module", module, self.module_name)
        for expr in self.pos_arguments:
            expr.prepare_step(module, None, None)
        for _, exprs in self.kw_arguments:
            for expr in exprs:
                expr.prepare_step(module, None, None)
        #print("Use.prepare_used_module", module, self.module_name,
        #      "done with arguments")

        #print(module, "use passing constant module parameters")

        def pass_pos_args(pb, arg_location, args):
            if pb is None:
                max_pb_args = 0
            else:
                max_pb_args = len(pb.required_params) + len(pb.optional_params)
            if max_pb_args < len(args):
                location = args[max_pb_args]
                scanner.syntax_error("Too many arguments passed to module",
                                     location.lexpos, location.lineno,
                                     location.filename)
            if pb is None:
                return

            if len(pb.required_params) > len(args):
                if args:
                    location = args[-1]
                else:
                    location = arg_location
                scanner.syntax_error("Not enough arguments passed to module",
                                     location.lexpos, location.lineno,
                                     location.filename)

            for p, a in zip_longest(pb.gen_parameters(), args):
                if a is None:
                    p.passed = False
                else:
                    p.passed = True
                    if a.get_step().immediate:
                        p.variable.immediate = True
                        p.variable.value = a.get_step().value
            pb.passed = True

        pass_pos_args(self.module.pos_param_block, self.name,
                      self.pos_arguments)
        kws_passed = set()
        for keyword, args in self.kw_arguments:
            if keyword not in self.module.kw_parameters:
                scanner.syntax_error("Module does not have this KEYWORD",
                                     keyword.lexpos, keyword.lineno,
                                     keyword.filename)
            pass_pos_args(self.module.kw_parameters[keyword], keyword, args)
            kws_passed.add(keyword)

        for keyword, pb in self.module.kw_parameters.items():
            if keyword not in kws_passed:
                if not pb.optional:
                    scanner.syntax_error(
                      f"Missing required KEYWORD -- {keyword.value}",
                      self.name.lexpos, self.name.lineno, self.name.filename)
                pb.passed = False

        self.module.prepare_module()
        self.run_hook("prepare_used_module", module)
        #print("Use.prepare_used_module", module, self.module_name, "done")

    @property
    def type(self):
        return self.module.type

    def get_step(self):
        return self.module


class Typedef(Entity):
    r'''type is either:

       (FUNCTION, taking_opt, returning_opt)
    or (SUBROUTINE, taking_opt)
    or (LABEL, taking_opt)
    or IDENT
    or MODULE
    '''

    is_module = False

    def __init__(self, ident, type):
        Entity.__init__(self, ident)
        self.type = type

    def __repr__(self):
        return f"<Typedef {self.name.value} {self.type}>"

    def dump_details(self, f):
        super().dump_details(f)
        print(f" type={self.type}", end='', file=f)

    def do_prepare(self, module):
        super().do_prepare(module)
        self.type.prepare(module)


class Type(Symtable):
    def get_type(self):
        return self

    def is_numeric(self):
        return False

    def is_integer(self):
        return False

    def is_float(self):
        return False

    def is_string(self):
        return False

    def is_boolean(self):
        return False

    def is_module(self):
        return False

    def can_take_type(self, arg_type, report_arg_type=True):
        r'''Check and report any type mismatches.

        If there are any mismatches, the syntax error is reported against
        `arg_type` if `report_arg_type` is True, else against self.
        '''
        my_t = self.get_type()
        arg_t = arg_type.get_type()
        if my_t is arg_t:
            # same type!
            return True
        if type(my_t) != type(arg_t):
            return False
        return my_t._can_take_type(arg_t, report_arg_type)


class Builtin_type(Type):
    def __init__(self, name):
        self.name = name.lower()  # str

    def __repr__(self):
        return f"<Builtin_type {self.name}>"

    def is_numeric(self):
        return self.name in ('float', 'integer')

    def is_integer(self):
        return self.name == 'integer'

    def is_float(self):
        return self.name == 'float'

    def is_string(self):
        return self.name == 'string'

    def is_boolean(self):
        return self.name == 'boolean'

    def is_module(self):
        return self.name == 'module'

    def _can_take_type(self, arg_type, report_arg_type):
        if not (self.name == arg_type.name or \
                self.name == 'float' and arg_type.name == 'integer'):
            if report_arg_type:
                # raises syntax_error on arg_type
                scanner.syntax_error("Incompatible type",
                                     arg_type.lexpos, arg_type.lineno,
                                     arg_type.filename)
            else:
                # raises syntax_error on self
                scanner.syntax_error("Incompatible type",
                                     self.lexpos, self.lineno, self.filename)


class Typename_type(Type):
    def __init__(self, ident):
        self.ident = ident

    def __repr__(self):
        return f"<Typename {self.ident.value}>"

    def get_type(self):
        r'Only valid after prepared.'
        return self.typedef.type.get_type()

    def do_prepare(self, module):
        super().do_prepare(module)

        # types can not be passed as module parameters, so this will be the
        # same result for all module instances...
        self.typedef = lookup(self.ident, module)
        if not isinstance(self.typedef, Typedef):
            scanner.syntax_error("Must be defined as a TYPE, "
                                   f"not a {self.typedef.__class__.__name__}",
                                 self.ident.lexpos, self.ident.lineno,
                                 self.ident.filename)

    def is_numeric(self):
        return self.typedef.type.is_numeric()

    def is_integer(self):
        return self.typedef.type.is_integer()

    def is_float(self):
        return self.typedef.type.is_float()

    def is_string(self):
        return self.typedef.type.is_string()

    def is_boolean(self):
        return self.typedef.type.is_boolean()

    def is_module(self):
        return self.typedef.type.is_module()


class Label_type(Type):
    r'''
    self.label_type is "subroutine", "function", "label",
                       "native_subroutine" or "native_function"
    self.required_params is (type, ...)
    self.optional_params is (type, ...)
    self.kw_params is {KEYWORD_TOKEN: (kw_optional, (type, ...), (type, ...))}
    self.return_types is ((req, opt), ((keyword_token, (req, opt)), ...))
    '''
    def __init__(self, label_type, taking_blocks, return_types=None):
        self.label_type = label_type.lower()

        if taking_blocks is None:
            self.required_params = self.optional_params = ()
            self.kw_params = {}
        else:
            assert len(taking_blocks) == 2
            assert len(taking_blocks[0]) == 2
            self.required_params, self.optional_params = taking_blocks[0]
            self.kw_params = {}
            for keyword, (req, opt) in taking_blocks[1]:
                if keyword.value[0] == '?':
                    self.kw_params[keyword] = (True, req, opt)
                else:
                    self.kw_params[keyword] = (False, req, opt)
        if self.label_type in ('subroutine', 'native_subroutine'):
            self.return_label_type = Label_type('label', None)
        elif self.label_type in ('function', 'native_function'):
            self.return_types = return_types
            self.return_label_type = Label_type('label', return_types)

    def __repr__(self):
        info = []
        if self.required_params:
            info.append(f"required_params: {self.required_params}")
        if self.optional_params:
            info.append(f"optional_params: {self.optional_params}")
        if self.kw_params:
            info.append(f"kw_params: {self.kw_params}")
        if hasattr(self, 'return_types'):
            info.append(f"returning: {self.return_types}")
        if info:
            return f"<Label_type {self.label_type} {' '.join(info)}>"
        return f"<Label_type {self.label_type}>"

    def do_prepare(self, module):
        super().do_prepare(module)
        def prepare_type(t):
            t.prepare(module)
            return t
        for t in self.required_params:
            t.prepare(module)
        for t in self.optional_params:
            t.prepare(module)
        for (_, req, opt) in self.kw_params.values():
            for t in req:
                t.prepare(module)
            for t in opt:
                t.prepare(module)
        if hasattr(self, 'return_label_type'):
            self.return_label_type.prepare(module)
        # self.return_types have already been passed to the Label_type for
        # return_label_type and have been prepared by that Label_type.

    def ok_as_return_for(self, fn_subr_type):
        r'''
        Assumes I'm at fault if there are any mismatches.
        '''
        fn_ret_t = fn_subr_type.get_type().return_label_type.get_type()
        return fn_ret_t.can_take_type(self)

    def _can_take_type(self, arg_type, report_arg_type):
        # I am a LABEL variable, and arg_type is an actual LABEL.  Can arg_type
        # safely be assigned to this variable?
        #
        # I.e., do I provide all of args that arg_type requires, and can
        # arg_type accept all of the args that I might provide?
        #
        # Finally, if I expect a return, can my return accept the arg_type
        # return?  I.e., can the arg_type return label variable take my return
        # label?

        if (self.label_type == 'label') != (arg_type.label_type == 'label'):
            # Must both be labels, or neither labels; otherwise one expects to
            # return and the other doesn't.
            if report_arg_type:
                scanner.syntax_error(
                  "Expected LABEL" if self.label_type == 'label'
                                   else "Expected SUBROUTINE or FUNCTION",
                  arg_type.lexpos, arg_type.lineno, arg_type.filename)
            else:
                scanner.syntax_error(
                  "Expected LABEL" if arg_type.label_type == 'label'
                                   else "Expected SUBROUTINE or FUNCTION",
                  self.lexpos, self.lineno, self.filename)

        arg_type.satisfied_by(self, self.required_params, self.optional_params,
                              self.kw_params, not report_arg_type)

        # For subroutines and functions, check the return_label_type
        if self.label_type != 'label':  # then arg_type is not 'label' either
            # Can the arg_type take my return label to return to?
            arg_type.return_label_type.can_take_type(self.return_label_type,
                                                     not report_arg_type)

    def satisfied_by(self, arg_location,
                     req, opt=(), kw_params={}, report_arg_type=True):
        r'''Do req, opt, kw_params satisfy my parameter needs?
        
        Without anything extra that I don't know about?

        kw_params is {KEYWORD_TOKEN: (kw_optional, (type, ...), (type, ...))}

        Does not check return types.

        If there are any mismatches, `result` determines what to do:
            
            - 'report_arg_type' raises syntax_error on req/opt/kw_params
            - 'report_self' raises syntax_error on self

        Returns None if OK.

        Returns tuple of indexes to the first faulty parameter.  The first
        index being 0 for req, 1 for opt and 2 for kw_params.

        Returns None if there are no problems.
        '''

        def check_pos_params(receiving_req, receiving_opt,
                             sending_req, sending_opt):
            # receiving is always from self, sending from req/opt/kw_params.
            if len(sending_req) + len(sending_opt) > \
               len(receiving_req) + len(receiving_opt):
                # receiving type must be able to take max number of params
                max_rec_len = len(receiving_req) + len(receiving_opt)
                if report_arg_type:
                    if len(sending_req) > max_rec_len:
                        arg = sending_req[max_rec_len]
                    else:
                        arg = sending_opt[max_rec_len - len(sending_req)]
                    scanner.syntax_error("Too many arguments",
                                         arg.lexpos, arg.lineno, arg.filename)
                else:
                    if receiving_opt:
                        rec = receiving_opt[-1]
                    elif receiving_req:
                        rec = receiving_req[-1]
                    else:
                        rec = self
                    scanner.syntax_error(
                      "Not enough parameters declared; "
                      f"got {max_rec_len}, "
                      f"expected {len(sending_req) + len(sending_opt)}",
                      rec.lexpos, rec.lineno, rec.filename)
            if len(sending_req) < len(receiving_req):
                # receiving type must be able to take min number of params
                if report_arg_type:
                    if sending_req:
                        arg = sending_req[-1]
                    else:
                        arg = arg_location
                    scanner.syntax_error(
                      "Not enough required parameters declared; "
                      f"got {len(sending_req)}, expected {len(receiving_req)}",
                      arg.lexpos, arg.lineno, arg.filename)
                else:
                    arg = receiving_req[len(sending_req)]
                    scanner.syntax_error(
                      "Too many required parameters declared",
                      arg.lexpos, arg.lineno, arg.filename)
            for sending_param, receiving_param \
             in zip(chain(sending_req, sending_opt),
                    chain(receiving_req, receiving_opt)):
                receiving_param.get_type().can_take_type(sending_param,
                                                         report_arg_type)

        # Check positonal parameters
        check_pos_params(self.required_params, self.optional_params, req, opt)

        # Check kw_params
        sending_req_kws = set()
        for keyword, (kw_optional, req, opt) in kw_params.items():
            if keyword not in self.kw_params:
                if report_arg_type:
                    scanner.syntax_error("Undeclared KEYWORD",
                                         keyword.lexpos, keyword.lineno,
                                         keyword.filename)
                else:
                    scanner.syntax_error(f"Missing KEYWORD -- {keyword.value}",
                                         self.lexpos, self.lineno,
                                         self.filename)
            my_kw_optional, my_req, my_opt = self.kw_params[keyword]
            if kw_optional:
                if not my_kw_optional:
                    if report_arg_type:
                        scanner.syntax_error("Must not be optional KEYWORD",
                                             keyword.lexpos, keyword.lineno,
                                             keyword.filename)
                    else:
                        for kw in self.kw_params.keys():
                            if kw == keyword:
                                scanner.syntax_error("Must be optional KEYWORD",
                                                     kw.lexpos, kw.lineno,
                                                     kw.filename)
                        assert False, f"Couldn't find KEYWORD {keyword}"
            else:
                sending_req_kws.add(keyword)
            check_pos_params(my_req, my_opt, req, opt)

        # Does I have any required kws that may not be provided?
        for my_keyword, (my_kw_optional, _, _) in self.kw_params.items():
            if not my_kw_optional and my_keyword not in sending_req_kws:
                if report_arg_type:
                    for kw in self.kw_params.keys():
                        if kw == my_keyword:
                            scanner.syntax_error("Must be required KEYWORD",
                                                 kw.lexpos, kw.lineno,
                                                 kw.filename)
                            break
                    else:
                        scanner.syntax_error(
                          f"Missing required KEYWORD -- {my_keyword.value}",
                          arg_location.lexpos, arg_location.lineno,
                          arg_location.filename)
                else:
                    scanner.syntax_error("Must not be required KEYWORD",
                                         my_keyword.lexpos, my_keyword.lineno,
                                         my_keyword.filename)

    def satisfied_by_arguments(self, arg_location, pos_arguments,
                               kw_arguments=()):
        r'''Checks if arguments are OK for me.

        kw_arguments is ((KEYWORD_TOKEN, (primary, ...)), ...)

        If there are any mismatches, a syntax_error is reported on the
        arguments.

        Does not check return type.
        '''
        class Type_proxy:
            r'''Exposes the expr.type preserving the lexpos, lineno and
            filename of the expr for syntax error reporting.
            '''
            def __init__(self, expr):
                self.expr = expr

            @property
            def lexpos(self):
                return self.expr.lexpos

            @property
            def lineno(self):
                return self.expr.lineno

            @property
            def filename(self):
                return self.expr.filename

            def get_type(self):
                return self.expr.type.get_type()

        self.satisfied_by(arg_location,
                          tuple(Type_proxy(e) for e in pos_arguments),
                          (),
                          {keyword: (False, 
                                     tuple(Type_proxy(e)
                                           for e in pos_arguments),
                                     ())
                           for keyword, pos_arguments in kw_arguments})


class Param_block(Symtable):
    r'''
    self.passed is set to True/False at compile time for module parameters.
    '''
    def __init__(self, name=None, optional=False):
        self.name = name  # token
        self.required_params = []
        self.optional_params = []
        self.optional = optional

    def dump_details(self, f):
        super().dump_details(f)
        if self.name is not None:
            print(' ', self.name.value, sep='', end='', file=f)
        if self.optional:
            print(" optional", end='', file=f)

    def dump_contents(self, f, indent):
        super().dump_contents(f, indent)
        for p in self.required_params:
            p.dump(f, indent+2)
        for p in self.optional_params:
            p.dump(f, indent+2)

    def add_parameter(self, param):
        if isinstance(param, Optional_parameter):
            param.param_pos_number = \
              len(self.required_params) + len(self.optional_params)
            self.optional_params.append(param)
        else:  # required parameter
            assert not self.optional_params
            param.param_pos_number = len(self.required_params)
            self.required_params.append(param)

    def gen_parameters(self):
        r'''Generates all parameter objects, both required and optional.
        '''
        yield from self.required_params
        yield from self.optional_params

    def lookup_param(self, ident, error_not_found=True):
        r'''Returns None if not found, unless error_not_found.
        '''
        lname = ident.value.lower()
        for p in self.gen_parameters():
            if lname == p.name.value.lower():
                return p
        if error_not_found:
            scanner.syntax_error("Parameter Not Found",
                                 ident.lexpos, ident.lineno, ident.filename)
        return None

    def do_prepare(self, module):
        super().do_prepare(module)
        #print("Param_block.do_prepare")
        for p in self.gen_parameters():
            #print("Param_block.do_prepare", p)
            p.prepare(module)

    def assign_passed_bits(self, next_bit_number):
        def get_bit_number():
            nonlocal next_bit_number
            ans = next_bit_number
            next_bit_number += 1
            return ans
        if self.optional:
            self.kw_passed_bit = get_bit_number()
        for p in self.optional_params:
            p.passed_bit = get_bit_number()
        return next_bit_number

    def as_taking_block(self):
        r'Must run prepare first!'
        required_types = tuple(p.type for p in self.required_params)
        optional_types = tuple(p.type for p in self.optional_params)
        if self.name is None:
            return required_types, optional_types
        return self.name, (required_types, optional_types)


class Namespace(Symtable):
    r'''Collection of named Entities.
    '''
    def __init__(self, name):
        self.name = name
        self.names = OrderedDict()
        #print(f"scanner.Namespaces.append({ident})")
        scanner.Namespaces.append(self)
        self.entities_prepared = False

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name}>"

    def filter(self, cls):
        return (entity
                for entity in self.names.values()
                 if type(entity) == cls)

    def lookup(self, ident, error_not_found=True):
        r'''Look up ident in self.names.

        if not found:
            if error_not_found: generate scanner.syntax_error
            else: return None
        '''
        lname = ident.value.lower()
        #print(self.name, "lookup", lname, tuple(self.names.keys()))
        if lname in self.names:
            return self.names[lname]
        if error_not_found:
            scanner.syntax_error("Undefined name", ident.lexpos, ident.lineno)
        return None

    def set(self, ident, entity):
        r'''Stores entity in self.names under ident.

        Reports duplicate names through scanner.syntax_error.
        '''
        lname = ident.value.lower()
        if lname in self.names:
            print("other entity", self.names[lname])
            scanner.syntax_error("Duplicate definition",
                                 ident.lexpos, ident.lineno)
        self.names[lname] = entity

    def make_variable(self, ident):
        lname = ident.value.lower()
        if lname not in self.names:
            # Variable automatically places itself in self.names
            entity = Variable(ident)
        else:
            entity = self.names[lname]
            if not isinstance(entity, Variable):
                scanner.syntax_error(
                  f"Duplicate definition with {entity.__class__.__name__} "
                  f"on line {entity.name.lineno}",
                  ident.lexpos, ident.lineno)
        return entity

    def dump_contents(self, f, indent):
        for entity in self.names.values():
            entity.dump(f, indent)

    def prepare_entities(self):
        if not self.entities_prepared:
            self.entities_prepared = True
            self.do_prepare_entities()
            self.run_hook("prepare_entities")

    def do_prepare_entities(self):
        for obj in self.names.values():
            obj.prepare(self)


class Opmode(Namespace):
    def __init__(self, modules_seen=None):
        Namespace.__init__(self, scanner.file_basename())
        self.filename = scanner.filename()

        if modules_seen is not None:
            # {module_name: module}
            # ... does not have lowered() keys!
            self.modules_seen = modules_seen
        self.next_set_bit = 0
        self.register()

    def register(self):
        global Opmode_module
        Opmode_module = self

    def set_in_namespace(self):
        pass

    #def dump_details(self, f):
    #    super().dump_details(f)
    #    print(f" modules_seen: {','.join(self.modules_seen.keys())}",
    #          end='', file=f)

    def dump_contents(self, f, indent):
        super().dump_contents(f, indent)
        if not isinstance(self, Module):
            print(f"{indent_str(indent)}Modules:", file=f)
            indent += 2
            for name, module in self.modules_seen.items():
                print(f"{indent_str(indent)}{name}:", file=f)
                module.dump(f, indent + 2)

    def setup(self):
        print("setup linking uses")
        builtins = self.modules_seen['builtins']
        builtins.link_uses()
        self.link_uses()
        print("setup doing prepare")
        builtins.prepare_module()
        self.prepare_module()
        print("setup done")

    def link_uses(self):
        #print(self.name, self.__class__.__name__, "link_uses")
        for use in self.filter(Use):
            #print(self.name, "link_uses doing", use)
            use.copy_module()

    def prepare_module(self):
        #print(self.name, self.__class__.__name__, "prepare_module")
        self.do_prepare_module()
        self.run_hook("prepare_module")

    def do_prepare_module(self):
        #print("Opmode.do_prepare_module", self.__class__.__name__, self.name)
        self.prepare_entities()
        self.prepare(self)   # declared in With_parameters
        for use in self.filter(Use):
            #print(self.name, "link_uses doing", use)
            use.prepare_used_module(self)
        print(self.name, self.__class__.__name__,
              "number of var-set bits used", self.next_set_bit)


class With_parameters(Symtable):
    def __init__(self):
        global Last_parameter_obj
        self.pos_param_block = None
        self.current_param_block = None
        self.kw_parameters = OrderedDict()      # {keyword_token: Param_block}
        Last_parameter_obj = self

    def pos_parameter(self, param):
        if self.current_param_block is None:
            self.pos_param_block = Param_block()
            self.current_param_block = self.pos_param_block
        self.current_param_block.add_parameter(param)

    def kw_parameter(self, keyword, optional=False):
        r'`keyword` is a Token.'
        if keyword in self.kw_parameters:
            scanner.syntax_error("Duplicate keyword",
                                 keyword.lexpos, keyword.lineno)
        self.current_param_block = self.kw_parameters[keyword] = \
          Param_block(keyword, optional)

    def dump_contents(self, f, indent):
        for pb in self.gen_param_blocks():
            pb.dump(f, indent)
        super().dump_contents(f, indent)

    def gen_param_blocks(self):
        if self.pos_param_block is not None:
            yield self.pos_param_block
        yield from self.kw_parameters.values()

    def lookup_param(self, ident, error_not_found=True):
        r'''Lookup parameter name in all Param_blocks.

        Returns None if not found, unless error_not_found.
        '''
        for pb in self.gen_param_blocks():
            param = pb.lookup_param(ident, error_not_found=False)
            if param is not None:
                return param
        if error_not_found:
            scanner.syntax_error("Parameter Not Found",
                                 ident.lexpos, ident.lineno, ident.filename)

    def do_prepare(self, module):
        super().do_prepare(module)
        for pb in self.gen_param_blocks():
            pb.prepare(module)
        self.check_for_duplicate_names()
        self.assign_passed_bits()

    def check_for_duplicate_names(self):
        seen = set()
        for pb in self.gen_param_blocks():
            for p in pb.gen_parameters():
                lname = p.name.value.lower()
                if lname in seen:
                    scanner.syntax_error("Duplicate Parameter Name",
                                         p.name.lexpos, p.name.lineno,
                                         p.name.filename)
                seen.add(lname)

    def assign_passed_bits(self):
        next_bit_number = 0
        for pb in self.gen_param_blocks():
            next_bit_number = pb.assign_passed_bits(next_bit_number)
        self.bits_used = next_bit_number

    def as_taking_blocks(self):
        r'Must run prepare first!'
        if self.pos_param_block is None:
            pos_block = (), ()
        else:
            pos_block = self.pos_param_block.as_taking_block()
        return (pos_block,
                tuple(pb.as_taking_block()
                      for pb in self.kw_parameters.values()))


class Module(With_parameters, Opmode):
    r'''self.steps is a tuple of labels, statements and DLTs.
    '''
    type = Builtin_type("module")
    immediate = True

    def __init__(self):
        Opmode.__init__(self)
        With_parameters.__init__(self)

    def register(self):
        pass

    @property
    def value(self):
        return self

    def add_steps(self, steps):
        self.steps = steps

    def dump_contents(self, f, indent):
        super().dump_contents(f, indent)
        for step in self.steps:
            step.dump(f, indent)

    def do_prepare_module(self):
        super().do_prepare_module()

        # Make all module parameters constant variables.
        for pb in self.gen_param_blocks():
            for p in pb.gen_parameters():
                p.variable.constant = True

        last_label = None
        last_fn_subr = None
        for step, next_step in pairwise(self.steps):
            if isinstance(step, Subroutine):
                last_fn_subr = step
                last_label = step
            elif isinstance(step, Label) and not step.hidden:
                last_label = step
            assert last_label is not None
            step.prepare_step(self, last_label, last_fn_subr)
            if next_step is None or isinstance(next_step, Label):
                if not step.is_final():
                    scanner.syntax_error("Statement must not fall-through",
                                         step.lexpos, step.lineno,
                                         step.filename)
            else:
                if step.is_final():
                    scanner.syntax_error("Statement must fall-through",
                                         step.lexpos, step.lineno,
                                         step.filename)


class Step(Symtable):
    step_prepared = False

    def prepare_step(self, module, last_label, last_fn_subr):
        r'''Called once per instance.
        '''
        if not self.step_prepared:
            self.step_prepared = True
            self.do_prepare_step(module, last_label, last_fn_subr)
            self.run_hook("prepare_step", module, last_label, last_fn_subr)

    def do_prepare_step(self, module, last_label, last_fn_subr):
        r'''Override this in the subclasses.
        '''
        pass

    def get_step(self):
        return self


class Label(With_parameters, Step, Entity):
    immediate = True

    def __init__(self, ident, hidden=False):
        Entity.__init__(self, ident)
        With_parameters.__init__(self)
        self.hidden = hidden

    def do_prepare(self, module):
        #print(self.__class__.__name__, "do_prepare", self.name)
        super().do_prepare(module)
        self.type = Label_type(self.__class__.__name__, self.as_taking_blocks(),
                               self.get_return_types())
        self.type.prepare(module)

    def get_return_types(self):
        return None

    @property
    def value(self):
        return self

    def is_final(self):
        return False


class Subroutine(Label):
    pass


class Function(Subroutine):
    def __init__(self, ident):
        Subroutine.__init__(self, ident)
        self.return_types = (((Builtin_type(ident.type),), ()), ())

    def set_return_types(self, return_types):
        r'self.return_types is ((req, opt), ((keyword_token, (req, opt)), ...))'
        self.return_types = return_types

    def get_return_types(self):
        return self.return_types

    def dump_details(self, f):
        super().dump_details(f)
        print(f" return_types {self.return_types}", end='', file=f)


class Native_subroutine(With_parameters, Entity):
    def __init__(self, ident):
        Entity.__init__(self, ident)
        With_parameters.__init__(self)

    def add_lines(self, lines):
        self.lines = lines

    def do_prepare(self, module):
        super().do_prepare(module)
        self.type = Label_type(self.__class__.__name__,
                               self.as_taking_blocks(),
                               self.get_return_types())
        self.type.prepare(module)

    def get_return_types(self):
        return None


class Native_function(Native_subroutine):
    def __init__(self, ident):
        Native_subroutine.__init__(self, ident)
        self.return_type = Builtin_type(ident.type)

    def set_return_type(self, return_type):
        self.return_type = return_type

    def get_return_types(self):
        return (((self.return_type,), ()), ())

    def do_prepare(self, module):
        super().do_prepare(module)
        self.return_type.prepare(module)


class Statement(Step):
    arguments = {
        'continue': (),
        'set': ('lvalue', 'expr'),
        'goto': ('expr', ('*', 'expr')),
        'return': (('*', 'expr'), 'ignore', 'expr'),
    }

    formats = {
        'set': ('{0[0]} = {0[1]}',),
        'goto': ('goto {}',),
        'return': ('return {}',),
    }

    def __init__(self, lexpos, lineno, *args):
        self.lexpos = lexpos
        self.lineno = lineno
        self.filename = scanner.filename()
        self.args = args

    def is_final(self):
        return self.args[0] in ('goto', 'return', 'continue')

    def is_continue(self):
        return self.args[0] == 'continue'

    def dump_details(self, f):
        super().dump_details(f)
        print(f" lineno {self.lineno}", end='', file=f)
        print(f" {self.args}", end='', file=f)

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        def _prepare(obj):
            if isinstance(obj, Step):
                obj.prepare_step(module, last_label, last_fn_subr)
            elif isinstance(obj, (list, tuple)):
                for x in obj:
                    _prepare(x)
        _prepare(self.args)
        # FIX: add type checking


class Call_statement(Statement):
    # primary arguments [RETURNING_TO primary]
    #
    # arguments is ((primary, ...), kw_arguments)
    #
    # kw_arguments is ((KEYWORD_TOKEN, (primary, ...)), ...)
    def is_final(self):
        return len(self.args) > 2

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        fn_type = self.args[0].type.get_type()
        if len(self.args) == 2:
            self.returning_to = None
            if not isinstance(fn_type, Label_type) or \
               fn_type.label_type not in ('subroutine', 'native_subroutine'):
                scanner.syntax_error("Must be a SUBROUTINE",
                                     self.args[0].lexpos, self.args[0].lineno,
                                     self.args[0].filename)
        else:
            assert len(self.args) == 4

            self.returning_to = self.args[3]
            ret_to_t = self.returning_to.type.get_type()
            if not isinstance(ret_to_t, Label_type) or \
               ret_to_t.label_type != 'label':
                scanner.syntax_error("Must be a LABEL",
                                     self.returning_to.lexpos,
                                     self.returning_to.lineno,
                                     self.returning_to.filename)

            if not ret_to_t.required_params and \
               not ret_to_t.optional_params and \
               not ret_to_t.kw_params:
                # return label does not accept any parameters
                if not isinstance(fn_type, Label_type) or \
                   fn_type.label_type not in ('subroutine',
                                              'native_subroutine'):
                    scanner.syntax_error("Must be a SUBROUTINE",
                                         self.args[0].lexpos,
                                         self.args[0].lineno,
                                         self.args[0].filename)
            else:
                # return label does accept parameters
                if not ret_to_t.required_params and \
                   all(opt for opt, _, _ in ret_to_t.kw_params.values()):
                    # return label does not require any parameters
                    if not isinstance(fn_type, Label_type) or \
                       fn_type.label_type == 'label':
                        scanner.syntax_error("Must be a SUBROUTINE or FUNCTION",
                                             self.args[0].lexpos,
                                             self.args[0].lineno,
                                             self.args[0].filename)
                else:
                    # return label requires some parameters
                    if not isinstance(fn_type, Label_type) or \
                       fn_type.label_type not in ('function',
                                                  'native_function'):
                        scanner.syntax_error("Must be a FUNCTION",
                                             self.args[0].lexpos,
                                             self.args[0].lineno,
                                             self.args[0].filename)
                if not ret_to_t.ok_as_return_for(fn_type):
                    scanner.syntax_error("Incompatible RETURNING_TO: label",
                                         self.returning_to.lexpos,
                                         self.returning_to.lineno,
                                         self.returning_to.filename)

        fn_type.satisfied_by_arguments(self.args[0], self.args[1][0],
                                       self.args[1][1])


class Opeq_statement(Statement):
    # primary OPEQ primary
    def is_final(self):
        return False

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        if self.args[1][0] == '%':
            if not self.args[0].is_integer():
                scanner.syntax_error("Must be an integer type",
                                     self.args[0].lexpos, self.args[0].lineno,
                                     self.args[0].filename)
        elif self.args[1][0] == '^':
            if not self.args[0].is_float():
                scanner.syntax_error("Must be an float type",
                                     self.args[0].lexpos, self.args[0].lineno,
                                     self.args[0].filename)
        else:
            if not self.args[0].is_numeric():
                scanner.syntax_error("Must be a numeric type",
                                     self.args[0].lexpos, self.args[0].lineno,
                                     self.args[0].filename)
        if self.args[0].is_integer():
            if not self.args[2].is_integer():
                scanner.syntax_error("Must be an integer type",
                                     self.args[2].lexpos, self.args[2].lineno,
                                     self.args[2].filename)
        else:
            if not self.args[2].is_numeric():
                scanner.syntax_error("Must be a numeric type",
                                     self.args[2].lexpos, self.args[2].lineno,
                                     self.args[2].filename)


class Done_statement(Statement):
    # done [with: label]
    def is_final(self):
        return False

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        if len(self.args) > 1:
            self.label = lookup(self.args[2], module)
            if not isinstance(self.label, Subroutine):
                scanner.syntax_error("Must be a SUBROUTINE or FUNCTION",
                                     self.args[2].lexpos, self.args[2].lineno,
                                     self.args[2].filename)
        else:
            assert last_label is not None
            self.label = last_label


class Conditions(Step):
    r'''DLT conditions section.

    self.exprs is condition expressions in order from MSB to LSB in the mask.
    self.num_columns is the number of columns in the DLT.
    self.offset is the number of spaces between the '|' and the first column.
    self.column_masks has one list of masks for each column.
    self.dlt_mask is the dlt_mask Token (for future syntax errors).
    '''
    def __init__(self, conditions):
        r'conditions is ((mask, expr), ...)'
        self.compile_conditions(conditions)

    def compile_conditions(self, conditions):
        self.exprs = []  # exprs form bits in mask, ordered MSB to LSB
        self.offset = None
        for dlt_mask, expr in conditions:
            if self.offset is None:
                self.offset = len(dlt_mask.value) - len(dlt_mask.value.lstrip())
                self.num_columns = len(dlt_mask.value.strip())
                columns = [[] for _ in range(self.num_columns)]
            this_offset = len(dlt_mask.value) - len(dlt_mask.value.lstrip())
            if this_offset != self.offset:
                scanner.syntax_error("Condition flags don't start in the same "
                                     "column as previous condition",
                                     dlt_mask.lexpos + this_offset,
                                     dlt_mask.lineno,
                                     dlt_mask.filename)
            dlt_mask.value = dlt_mask.value.lstrip()
            dlt_mask.lexpos += this_offset
            if len(dlt_mask.value.strip()) != self.num_columns:
                scanner.syntax_error("Must have same number of condition flags "
                                     "as previous condition",
                                     dlt_mask.lexpos, dlt_mask.lineno,
                                     dlt_mask.filename)
            self.exprs.append(expr)
            for i, flag in enumerate(dlt_mask.value.strip()):
                if flag not in '-yYnN':
                    scanner.syntax_error("Illegal condition flag, "
                                         "expected 'y', 'n', or '-'",
                                         dlt_mask.lexpos + i, dlt_mask.lineno,
                                         dlt_mask.filename)
                columns[i].append(flag.upper())

        #print("exprs", self.exprs, "offset", self.offset,
        #      "num_columns", self.num_columns, "columns", columns)

        self.dlt_mask = dlt_mask

        # Generate column_masks.  Column_masks has one list of masks for each
        # column.
        self.column_masks = []
        for flags in columns:
            self.column_masks.append(self.gen_masks(flags))
        #print("column_masks", self.column_masks)

        # Check for duplicate condition flags
        seen = set()
        for i, masks in enumerate(self.column_masks):
            for mask in masks:
                if mask in seen:
                    scanner.syntax_error("Duplicate condition flags",
                                         self.dlt_mask.lexpos + i,
                                         self.dlt_mask.lineno,
                                         self.dlt_mask.filename)
                else:
                    seen.add(mask)

        # Check to insure all condition combinations were specified
        all_masks = frozenset(range(2**len(self.exprs)))
        #print("all_masks", all_masks, "seen", seen)
        unseen = [self.decode_mask(missing)
                  for missing in sorted(all_masks - seen)]
        if unseen:
            scanner.syntax_error("Missing condition flags (top to bottom): "
                                   + ', '.join(unseen),
                                 self.dlt_mask.lexpos + self.num_columns,
                                 self.dlt_mask.lineno,
                                 self.dlt_mask.filename)

    def gen_masks(self, flags, i=None):
        if not flags: return [0]
        if i is None: i = len(flags) - 1
        masks = []
        if flags[0] in 'Y-':
            masks += [2**i + mask for mask in self.gen_masks(flags[1:], i - 1)]
        if flags[0] in 'N-':
            masks += self.gen_masks(flags[1:], i - 1)
        #print(f"gen_masks({flags}, {i}) -> {masks}")
        return masks

    def decode_mask(self, mask):
        return ''.join([('Y' if 2**i & mask else 'N')
                        for i in range(self.num_columns - 1, -1, -1)])

    def sync_actions(self, actions):
        missing_columns = actions.apply_offset(self.offset, self.num_columns)
        if missing_columns:
            scanner.syntax_error("Missing action for this column",
                                 self.dlt_mask.lexpos + missing_columns[0],
                                 self.dlt_mask.lineno,
                                 self.dlt_mask.filename)

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        for expr in self.exprs:
            expr.prepare_step(module, last_label, last_fn_subr)
        for expr in self.exprs:
            if not expr.is_boolean():
                scanner.syntax_error("Must be boolean expression",
                                     expr.lexpos, expr.lineno, expr.filename)


class DLT_MAP(Step):
    r'''self.map is a Token whose value is the "X X..." map.
    '''
    def __init__(self, map):
        self.map = map

    def is_final(self):
        return False

    def is_continue(self):
        return False

    def assign_column_numbers(self, seen):
        r'''Creates self.column_numbers.

        Reports duplicate actions for any column.
        '''
        self.column_numbers = []
        for i, marker in enumerate(self.map.value.lower()):
            if marker == 'x':
                if i in seen:
                    scanner.syntax_error("Duplicate action for column",
                                         self.map.lexpos + i, self.map.lineno)
                self.column_numbers.append(i)

    def apply_offset(self, offset, num_columns):
        r'''Subtracts offset from each column_number in self.column_numbers.

        Checks that all column_numbers are >= offset and resulting
        column_number is < num_columns.

        Returns a list of the resulting column_numbers.
        '''
        for i in range(len(self.column_numbers)):
            if self.column_numbers[i] < offset or \
               self.column_numbers[i] - offset >= num_columns:
                scanner.syntax_error("Column marker does not match "
                                     "any column in DLT conditions section",
                                     self.map.lexpos + self.column_numbers[i],
                                     self.map.lineno)
            self.column_numbers[i] -= offset
        return self.column_numbers

    def dump_details(self, f):
        super().dump_details(f)
        print(f" {self.map.value}", end='', file=f)


class Actions(Step):
    def __init__(self, actions):
        r'self.actions is ((dlt_map | statement) ...)'
        self.actions = actions
        seen = set()
        self.final = True
        for action, next_action in pairwise(actions):
            if isinstance(action, DLT_MAP):
                action.assign_column_numbers(seen)
            elif action.is_continue():
                self.final = False
            if next_action is not None and not isinstance(next_action, DLT_MAP):
                if action.is_final():
                    scanner.syntax_error("Statement must fall-through",
                                         action.lexpos, action.lineno,
                                         action.filename)
        if not actions[-1].is_final():
            self.final = False

    def is_final(self):
        return self.final

    def apply_offset(self, offset, num_columns):
        r'''Subtracts offset from each column_number in self.actions.

        Checks that all column_numbers are >= offset and resulting
        column_number is < num_columns.

        Returns an ordered list of missing column_numbers.
        '''
        seen = set()
        for action in self.actions:
            if isinstance(action, DLT_MAP):
                seen.update(action.apply_offset(offset, num_columns))

        # Return missing column_numbers.
        ans = sorted(frozenset(range(num_columns)) - seen)
        return ans

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        for action in self.actions:
            action.prepare_step(module, last_label, last_fn_subr)


class DLT(Step):
    def __init__(self, conditions, actions):
        self.conditions = conditions    # Conditions instance
        self.actions = actions          # Actions instance
        conditions.sync_actions(actions)

    def is_continue(self):
        return False

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        self.conditions.prepare_step(module, last_label, last_fn_subr)
        self.actions.prepare_step(module, last_label, last_fn_subr)

    def is_final(self):
        return self.actions.is_final()


class Expr(Step):
    immediate = False   # True iff value known at compile time

    def __init__(self, lexpos, lineno):
        self.lexpos = lexpos
        self.lineno = lineno
        self.filename = scanner.filename()
        self.prelude_steps = []

    def is_numeric(self):
        return self.type.is_numeric()

    def is_integer(self):
        return self.type.is_integer()

    def is_float(self):
        return self.type.is_float()

    def is_string(self):
        return self.type.is_string()

    def is_boolean(self):
        return self.type.is_boolean()

    def is_module(self):
        return self.type.is_module()


class Literal(Expr):
    immediate = True

    def __init__(self, lexpos, lineno, value):
        Expr.__init__(self, lexpos, lineno)
        self.value = value
        if isinstance(value, bool):
            self.type = Builtin_type('boolean')
        elif isinstance(value, int):
            self.type = Builtin_type('integer')
        elif isinstance(value, float):
            self.type = Builtin_type('float')
        elif isinstance(value, str):
            self.type = Builtin_type('string')

    def __repr__(self):
        return f"<Literal {self.value!r}>"


class Reference(Expr):
    r'''An IDENT that references either a Variable or a Label.

    Type IDENTs are converted to Typename_types rather than References.
    '''
    def __init__(self, ident):
        Expr.__init__(self, ident.lexpos, ident.lineno)
        self.ident = ident

    def __repr__(self):
        return f"<Reference {self.ident.value}>"

    def get_step(self):
        return self.referent.get_step()

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)

        # These should be the same for all instances (since the type is
        # defined in the module and can't be passed in as a module parameter).
        self.referent = lookup(self.ident, module)
        self.type = self.referent.type
        #print("Reference", self.ident, "found", self.referent)


class Dot(Expr):
    def __init__(self, expr, ident):
        Expr.__init__(self, expr.lexpos, expr.lineno)
        self.expr = expr
        self.ident = ident

    def __repr__(self):
        return f"<Dot {self.expr} {self.ident.value}>"

    # self.type has to be done for each instance...
    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        self.expr.prepare_step(module, last_label, last_fn_subr)
        if not self.expr.get_step().immediate or \
           not isinstance(self.expr.get_step().value, Module):
            scanner.syntax_error("Module expected",
                                 self.expr.lexpos, self.expr.lineno,
                                 self.expr.filename)
        self.referent = self.expr.get_step().value.lookup(self.ident)
        self.type = self.referent.type
        if self.referent.get_step().immediate:
            self.immediate = True
            self.value = self.referent.get_step().value


class Subscript(Expr):
    def __init__(self, array_expr, subscript_expr):
        Expr.__init__(self, array_expr.lexpos, array_expr.lineno)
        self.array_expr = array_expr
        self.subscript_expr = subscript_expr

    def __repr__(self):
        return f"<Subscript {self.array_expr} {self.subscript_expr}>"

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        self.array_expr.prepare_step(module, last_label, last_fn_subr)
        self.subscript_expr.prepare_step(module, last_label, last_fn_subr)
        self.type = self.array_expr.type


class Got_keyword(Expr):
    r'''self.label and self.bit_number set in prepare.
    '''
    type = Builtin_type("boolean")

    def __init__(self, lexpos, lineno, keyword, label=None, module=False):
        Expr.__init__(self, lexpos, lineno)
        self.keyword = keyword  # Token
        self.label = label
        self.module = module

    def __repr__(self):
        return f"<Got_keyword {self.keyword.value}>"

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        if self.module:
            pb = module.kw_parameters.get(self.keyword)
        else:
            if self.label is None:
                self.label = last_label
            pb = self.label.kw_parameters.get(self.keyword)
        if pb is None:
            scanner.syntax_error("Keyword Not Found",
                                 self.keyword.lexpos, self.keyword.lineno,
                                 self.keyword.filename)
        if not pb.optional:
            scanner.syntax_error("Must be an optional keyword",
                                 self.keyword.lexpos, self.keyword.lineno,
                                 self.keyword.filename)
        self.bit_number = pb.kw_passed_bit
        if self.module:
            self.immediate = True
            self.value = pb.passed


class Got_param(Expr):
    r'''self.label and self.bit_number set in prepare.
    '''
    type = Builtin_type("boolean")

    def __init__(self, lexpos, lineno, ident, label=None, module=False):
        Expr.__init__(self, lexpos, lineno)
        self.ident = ident
        self.label = label
        self.module = module

    def __repr__(self):
        return f"<Got_param {self.ident.value}>"

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        if self.module:
            obj = module
        else:
            if self.label is None:
                self.label = last_label
            obj = self.label
        found = False
        for pb in obj.gen_param_blocks():
            param = pb.lookup_param(self.ident, error_not_found=False)
            if param is not None:
                if isinstance(param, Optional_parameter):
                    self.bit_number = param.passed_bit
                    if self.module:
                        self.immediate = True
                        self.value = param.passed
                    break
                else:
                    scanner.syntax_error("Must be an optional parameter",
                                         self.ident.lexpos,
                                         self.ident.lineno,
                                         self.ident.filename)
        else:
            scanner.syntax_error("Parameter Not Found",
                                 self.ident.lexpos, self.ident.lineno,
                                 self.ident.filename)


class Call_fn(Expr):
    def __init__(self, fn, pos_arguments, kw_arguments):
        Expr.__init__(self, fn.lexpos, fn.lineno)
        self.fn = fn
        self.pos_arguments = pos_arguments  # (primary, ...)

        # ((KEYWORD_TOKEN, (primary, ...)), ...)
        self.kw_arguments = kw_arguments 

    def __repr__(self):
        return f"<Call_fn {self.fn} {self.pos_arguments} {self.kw_arguments}>"

    def do_prepare_step(self, module, last_label, last_fn_subr):
        # self.type has to be done for each instance...
        super().do_prepare_step(module, last_label, last_fn_subr)
        self.fn.prepare_step(module, last_label, last_fn_subr)
        fn_type = self.fn.type.get_type()
        if not isinstance(fn_type, Label_type) or \
           fn_type.label_type not in ('function', 'native_function') or \
           len(fn_type.return_types[0][0]) != 1 or \
           fn_type.return_types[0][1] or \
           fn_type.return_types[1]:
            scanner.syntax_error("Must be a FUNCTION returning a single value",
                                 self.fn.lexpos, self.fn.lineno,
                                 self.fn.filename)
        for expr in self.pos_arguments:
            expr.prepare_step(module, last_label, last_fn_subr)
        for _, pos_arguments in self.kw_arguments:
            for expr in pos_arguments:
                expr.prepare_step(module, last_label, last_fn_subr)
        fn_type.satisfied_by_arguments(self.fn, self.pos_arguments,
                                       self.kw_arguments)
        self.type = fn_type.return_types[0][0][0]


class Unary_expr(Expr):
    def __init__(self, lexpos, lineno, operator, expr):
        Expr.__init__(self, lexpos, lineno)
        self.operator = operator.lower()
        self.expr = expr

    def __repr__(self):
        return f"<Unary_expr {self.operator} {self.expr}>"

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        self.expr.prepare_step(module, last_label, last_fn_subr)
        if self.operator in ('-', 'abs'):
            if not self.expr.is_numeric():
                scanner.syntax_error("Must be a numeric type",
                                     self.expr.lexpos, self.expr.lineno,
                                     self.expr.filename)
            self.type = self.expr.type
            if self.expr.get_step().immedate:
                self.immediate = True
                if self.operator == '-':
                    self.value = -self.expr.get_step().value
                else:
                    self.value = abs(self.expr.get_step().value)
        elif self.operator == 'not':
            if not self.expr.is_boolean():
                scanner.syntax_error("Must be boolean",
                                     self.expr.lexpos, self.expr.lineno,
                                     self.expr.filename)
            self.type = Builtin_type("boolean")
            if self.expr.get_step().immedate:
                self.immediate = True
                self.value = not self.expr.get_step().value
        else:
            raise AssertionError(f"Unknown operator {self.operator}")


class Binary_expr(Expr):
    operator_map = {  # {operator: (result_type, arg_type, immediate_fn)}
        '^': ('float', 'number', lambda x, y: x**y),
        '*': ('numeric', 'number', lambda x, y: x * y),
        '/': ('float', 'number', lambda x, y: x / y),
        '//': ('integer', 'integer', lambda x, y: x // y),
        '%': ('integer', 'integer', lambda x, y: x % y),
        '+': ('numeric', 'number', lambda x, y: x + y),
        '-': ('numeric', 'number', lambda x, y: x - y),
        '<': ('boolean', 'number or string', lambda x, y: x < y),
        '<=': ('boolean', 'number or string', lambda x, y: x <= y),
        '<~=': ('boolean', 'float', lambda x, y: x < y or aeq(x, y)),
        '>': ('boolean', 'number or string', lambda x, y: x > y),
        '>=': ('boolean', 'number or string', lambda x, y: x >= y),
        '>~=': ('boolean', 'float', lambda x, y: x > y or aeq(x, y)),
        '==': ('boolean', 'number or string', lambda x, y: x == y),
        '~=': ('boolean', 'float', lambda x, y: aeq(x, y)),
        '!=': ('boolean', 'number or string', lambda x, y: x != y),
        '<>': ('boolean', 'number or string', lambda x, y: x != y),
        '!~=': ('boolean', 'float', lambda x, y: not aeq(x, y)),
        '<~>': ('boolean', 'float', lambda x, y: not aeq(x, y)),
    }

    def __init__(self, expr1, operator, expr2):
        Expr.__init__(self, expr1.lexpos, expr1.lineno)
        self.expr1 = expr1
        self.operator = operator
        self.expr2 = expr2

    def __repr__(self):
        return f"<Binary_expr {self.expr1} {self.operator} {self.expr2}>"

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        self.expr1.prepare_step(module, last_label, last_fn_subr)
        self.expr2.prepare_step(module, last_label, last_fn_subr)

        result_type, arg_type, immed_fn = self.operator_map[self.operator]

        if arg_type == 'integer':
            if not self.expr1.is_integer():
                scanner.syntax_error(f"Expected {arg_type} type",
                                     self.expr1.lexpos, self.expr1.lineno,
                                     self.expr1.filename)
            if not self.expr2.is_integer():
                scanner.syntax_error(f"Expected {arg_type} type",
                                     self.expr2.lexpos, self.expr2.lineno,
                                     self.expr2.filename)
        elif arg_type == 'float':    # at least one has to be float
            if not self.expr1.is_numeric():
                scanner.syntax_error("Expected number type",
                                     self.expr1.lexpos, self.expr1.lineno,
                                     self.expr1.filename)
            if not self.expr2.is_numeric():
                scanner.syntax_error("Expected number type",
                                     self.expr2.lexpos, self.expr2.lineno,
                                     self.expr2.filename)
            if not self.expr1.is_float() and not self.expr2.is_float():
                scanner.syntax_error(f"Expected {arg_type} type",
                                     self.expr1.lexpos, self.expr1.lineno,
                                     self.expr1.filename)
        elif arg_type == 'number':
            if not self.expr1.is_numeric():
                scanner.syntax_error("Expected number type",
                                     self.expr1.lexpos, self.expr1.lineno,
                                     self.expr1.filename)
            if not self.expr2.is_numeric():
                scanner.syntax_error("Expected number type",
                                     self.expr2.lexpos, self.expr2.lineno,
                                     self.expr2.filename)
        elif arg_type == 'number or string':
            if not self.expr1.is_numeric() and not self.expr1.is_string():
                scanner.syntax_error(f"Expected {arg_type} type, "
                                       f"got {self.expr1.type}",
                                     self.expr1.lexpos, self.expr1.lineno,
                                     self.expr1.filename)
            if not self.expr2.is_numeric() and not self.expr2.is_string():
                scanner.syntax_error(f"Expected {arg_type} type, "
                                       f"got {self.expr2.type}",
                                     self.expr2.lexpos, self.expr2.lineno,
                                     self.expr2.filename)
            if self.expr1.is_numeric() and not self.expr2.is_numeric() or \
               self.expr1.is_string() and not self.expr2.is_string():
                scanner.syntax_error(
                  f"{self.operator!r}: expression types don't match",
                  self.expr2.lexpos, self.expr2.lineno, self.expr2.filename)
        else:
            raise AssertionError(
                    f"Unknown arg_type: {arg_type} for {self.operator}")
        if result_type == 'numeric':
            self.type = \
              Builtin_type('integer'
                           if self.expr1.is_integer() and \
                              self.expr2.is_integer()
                           else 'float')
        else:
            self.type = Builtin_type(result_type)
        if self.expr1.get_step().immediate and self.expr2.get_step().immediate:
            self.immediate = True
            self.value = immed_fn(self.expr1.get_step().value,
                                  self.expr2.get_step().value)


class Return_label(Expr):
    def __init__(self, lexpos, lineno, label=None):
        #print("Return_label", lexpos, lineno, label)
        Expr.__init__(self, lexpos, lineno)
        self.label = label      # IDENT

    def do_prepare_step(self, module, last_label, last_fn_subr):
        super().do_prepare_step(module, last_label, last_fn_subr)
        if self.label is None:
            if last_fn_subr is None:
                scanner.syntax_error("Must follow a SUBROUTINE or FUNCTION",
                                     self.lexpos, self.lineno, self.filename)
            self.label = last_fn_subr
        else:
            self.label = module.lookup(self.label)
            if not isinstance(self.label, Subroutine):
                scanner.syntax_error("Must be a SUBROUTINE or FUNCTION",
                                     self.label.lexpos, self.label.lineno,
                                     self.label.filename)
        self.type = self.label.type.return_label_type


def indent_str(indent):
    return " "*indent


def lookup(ident, module):
    #print("lookup", ident, module)
    obj = module.lookup(ident, error_not_found=False)
    if obj is not None:
        return obj
    obj = Opmode_module.lookup(ident, error_not_found=False)
    if obj is not None:
        return obj
    obj = Opmode_module.modules_seen['builtins'] \
                       .lookup(ident, error_not_found=False)
    if obj is not None:
        return obj
    scanner.syntax_error("Not found",
                         ident.lexpos, ident.lineno, ident.filename)

