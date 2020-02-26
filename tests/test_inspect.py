from functools import partial
import os
import sys

import _inspect_fixture as i_f
import pytest

from falcon import inspect, routing


def get_app(asgi, cors=True, **kw):
    if asgi:
        from falcon.asgi import App as AsyncApp
        return AsyncApp(cors_enable=cors, **kw)
    else:
        from falcon import App
        return App(cors_enable=cors, **kw)


def make_app():
    app = get_app(False, cors=True)
    app.add_middleware(i_f.MyMiddleware())
    app.add_middleware(i_f.OtherMiddleware())

    app.add_sink(i_f.sinkFn, '/sink_fn')
    app.add_sink(i_f.SinkClass(), '/sink_cls')

    app.add_error_handler(RuntimeError, i_f.my_error_handler)

    app.add_route('/foo', i_f.MyResponder())
    app.add_route('/foo/{id}', i_f.MyResponder(), suffix='id')
    app.add_route('/bar', i_f.OtherResponder(), suffix='id')

    app.add_static_route('/fal', os.path.abspath('falcon'))
    app.add_static_route('/tes', os.path.abspath('tests'), fallback_filename='conftest.py')
    return app


def make_app_async():
    app = get_app(True, cors=True)
    app.add_middleware(i_f.MyMiddlewareAsync())
    app.add_middleware(i_f.OtherMiddlewareAsync())

    app.add_sink(i_f.sinkFn, '/sink_fn')
    app.add_sink(i_f.SinkClass(), '/sink_cls')

    app.add_error_handler(RuntimeError, i_f.my_error_handler_async)

    app.add_route('/foo', i_f.MyResponderAsync())
    app.add_route('/foo/{id}', i_f.MyResponderAsync(), suffix='id')
    app.add_route('/bar', i_f.OtherResponderAsync(), suffix='id')

    app.add_static_route('/fal', os.path.abspath('falcon'))
    app.add_static_route('/tes', os.path.abspath('tests'), fallback_filename='conftest.py')
    return app


class TestInspectApp:
    def test_empty_app(self, asgi):
        ai = inspect.inspect_app(get_app(asgi, False))

        assert ai.routes == []
        assert ai.middleware.middleware_tree.request == []
        assert ai.middleware.middleware_tree.resource == []
        assert ai.middleware.middleware_tree.response == []
        assert ai.middleware.middleware_classes == []
        assert ai.middleware.independent is True
        assert ai.static_routes == []
        assert ai.sinks == []
        assert len(ai.error_handlers) == 3
        assert ai.asgi is asgi

    def test_dependent_middlewares(self, asgi):
        app = get_app(asgi, cors=False, independent_middleware=False)
        ai = inspect.inspect_app(app)
        assert ai.middleware.independent is False

    def test_app(self, asgi):
        ai = inspect.inspect_app(make_app_async() if asgi else make_app())

        assert len(ai.routes) == 3
        assert len(ai.middleware.middleware_tree.request) == 2
        assert len(ai.middleware.middleware_tree.resource) == 1
        assert len(ai.middleware.middleware_tree.response) == 3
        assert len(ai.middleware.middleware_classes) == 3
        assert len(ai.static_routes) == 2
        assert len(ai.sinks) == 2
        assert len(ai.error_handlers) == 4
        assert ai.asgi is asgi

    def test_routes(self, asgi):
        routes = inspect.inspect_routes(make_app_async() if asgi else make_app())

        def test(r, p, cn, ml, fnt):
            assert isinstance(r, inspect.RouteInfo)
            assert r.path == p
            if asgi:
                cn += 'Async'
            assert r.class_name == cn
            assert '_inspect_fixture.py' in r.source_info

            for m in r.methods:
                assert isinstance(m, inspect.RouteMethodInfo)
                internal = '_inspect_fixture.py' not in m.source_info
                assert m.internal is internal
                if not internal:
                    assert m.method in ml
                    assert '_inspect_fixture.py' in m.source_info
                    assert m.function_name == fnt.format(m.method).lower()

        test(routes[0], '/foo', 'MyResponder', ['GET', 'POST', 'DELETE'], 'on_{}')
        test(routes[1], '/foo/{id}', 'MyResponder', ['GET', 'PUT', 'DELETE'], 'on_{}_id')
        test(routes[2], '/bar', 'OtherResponder', ['POST'], 'on_{}_id')

    def test_static_routes(self, asgi):
        routes = inspect.inspect_static_routes(make_app_async() if asgi else make_app())

        assert all(isinstance(sr, inspect.StaticRouteInfo) for sr in routes)
        assert routes[-1].prefix == '/fal/'
        assert routes[-1].directory == os.path.abspath('falcon')
        assert routes[-1].fallback_filename is None
        assert routes[-2].prefix == '/tes/'
        assert routes[-2].directory == os.path.abspath('tests')
        assert routes[-2].fallback_filename.endswith('conftest.py')

    def test_sync(self, asgi):
        sinks = inspect.inspect_sinks(make_app_async() if asgi else make_app())

        assert all(isinstance(s, inspect.SinkInfo) for s in sinks)
        assert sinks[-1].prefix == '/sink_fn'
        assert sinks[-1].name == 'sinkFn'
        assert '_inspect_fixture.py' in sinks[-1].source_info
        assert sinks[-2].prefix == '/sink_cls'
        assert sinks[-2].name == 'SinkClass'
        assert '_inspect_fixture.py' in sinks[-2].source_info

    @pytest.mark.skipif(sys.version_info < (3, 6), reason='dict order is not stable')
    def test_error_handler(self, asgi):
        errors = inspect.inspect_error_handlers(make_app_async() if asgi else make_app())

        assert all(isinstance(e, inspect.ErrorHandlerInfo) for e in errors)
        assert errors[-1].error == 'RuntimeError'
        assert errors[-1].name == 'my_error_handler_async' if asgi else 'my_error_handler'
        assert '_inspect_fixture.py' in errors[-1].source_info
        assert errors[-1].internal is False
        for eh in errors[:-1]:
            assert eh.internal
            assert eh.error in ('Exception', 'HTTPStatus', 'HTTPError')

    def test_middleware(self, asgi):
        mi = inspect.inspect_middlewares(make_app_async() if asgi else make_app())

        def test(m, cn, ml, inte):
            assert isinstance(m, inspect.MiddlewareClassInfo)
            assert m.name == cn
            if inte:
                assert '_inspect_fixture.py' not in m.source_info
            else:
                assert '_inspect_fixture.py' in m.source_info

            for mm in m.methods:
                assert isinstance(mm, inspect.MiddlewareMethodInfo)
                if inte:
                    assert '_inspect_fixture.py' not in mm.source_info
                else:
                    assert '_inspect_fixture.py' in mm.source_info
                assert mm.function_name in ml

        test(
            mi.middleware_classes[0],
            'CORSMiddleware',
            ['process_response_async'] if asgi else ['process_response'],
            True,
        )
        test(
            mi.middleware_classes[1],
            'MyMiddlewareAsync' if asgi else 'MyMiddleware',
            ['process_request', 'process_resource', 'process_response'],
            False,
        )
        test(
            mi.middleware_classes[2],
            'OtherMiddlewareAsync' if asgi else 'OtherMiddleware',
            ['process_request', 'process_resource', 'process_response'],
            False,
        )

    def test_middleware_tree(self, asgi):
        mi = inspect.inspect_middlewares(make_app_async() if asgi else make_app())

        def test(tl, names, cls):
            for (t, n, c) in zip(tl, names, cls):
                assert isinstance(t, inspect.MiddlewareTreeItemInfo)
                assert t.name == n
                assert t.class_name == c

        assert isinstance(mi.middleware_tree, inspect.MiddlewareTreeInfo)

        test(
            mi.middleware_tree.request,
            ['process_request'] * 2,
            [n + 'Async' if asgi else n for n in ['MyMiddleware', 'OtherMiddleware']],
        )
        test(
            mi.middleware_tree.resource,
            ['process_resource'],
            ['MyMiddlewareAsync' if asgi else 'MyMiddleware'],
        )
        test(
            mi.middleware_tree.response,
            [
                'process_response',
                'process_response',
                'process_response_async' if asgi else 'process_response',
            ],
            [
                'OtherMiddlewareAsync' if asgi else 'OtherMiddleware',
                'MyMiddlewareAsync' if asgi else 'MyMiddleware',
                'CORSMiddleware',
            ],
        )


class TestRouter:
    def test_compiled_partial(self):
        r = routing.CompiledRouter()
        r.add_route('/foo', i_f.MyResponder())
        # override a method with a partial
        r._roots[0].method_map['GET'] = partial(r._roots[0].method_map['GET'])
        ri = inspect.inspect_compiled_router(r)

        for m in ri[0].methods:
            if m.method == 'GET':
                assert '_inspect_fixture' in m.source_info

    def test_compiled_no_method_map(self):
        r = routing.CompiledRouter()
        r.add_route('/foo', i_f.MyResponder())
        # clear the method map
        r._roots[0].method_map.clear()
        ri = inspect.inspect_compiled_router(r)

        assert ri[0].path == '/foo'
        assert ri[0].class_name == 'MyResponder'
        assert ri[0].methods == []

    def test_register_router_not_found(self, monkeypatch):
        monkeypatch.setattr(inspect, '_supported_routers', {})

        app = get_app(False)
        with pytest.raises(TypeError, match='Unsupported router class'):
            inspect.inspect_routes(app)

    def test_register_other_router(self, monkeypatch):
        monkeypatch.setattr(inspect, '_supported_routers', {})

        app = get_app(False)
        app._router = i_f.MyRouter()

        @inspect.register_router(i_f.MyRouter)
        def print_routes(r):
            assert r is app._router
            return [inspect.RouteInfo('foo', 'bar', '', [])]

        ri = inspect.inspect_routes(app)

        assert ri[0].source_info == ''
        assert ri[0].path == 'foo'
        assert ri[0].class_name == 'bar'
        assert ri[0].methods == []

    def test_register_router_multiple_time(self, monkeypatch):
        monkeypatch.setattr(inspect, '_supported_routers', {})

        @inspect.register_router(i_f.MyRouter)
        def print_routes(r):
            return []

        with pytest.raises(ValueError, match='Another function is already registered'):
            @inspect.register_router(i_f.MyRouter)
            def print_routes2(r):
                return []


def test_info_class_repr_to_string():
    ai = inspect.inspect_app(make_app())

    assert str(ai) == ai.to_string()
    assert str(ai.routes[0]) == ai.routes[0].to_string()
    assert str(ai.routes[0].methods[0]) == ai.routes[0].methods[0].to_string()
    assert str(ai.middleware) == ai.middleware.to_string()
    s = str(ai.middleware.middleware_classes[0])
    assert s == ai.middleware.middleware_classes[0].to_string()
    s = str(ai.middleware.middleware_tree.request[0]) 
    assert s == ai.middleware.middleware_tree.request[0].to_string()
    assert str(ai.static_routes[0]) == ai.static_routes[0].to_string()
    assert str(ai.sinks[0]) == ai.sinks[0].to_string()
    assert str(ai.error_handlers[0]) == ai.error_handlers[0].to_string()


class TestInspectVisitor:
    def test_inspect_visitor(self):
        iv = inspect.InspectVisitor()
        with pytest.raises(RuntimeError, match='This visitor does not support'):
            iv.process(123)
        with pytest.raises(RuntimeError, match='This visitor does not support'):
            iv.process(inspect.RouteInfo('f', 'o', 'o', []))

    def test_process(self):
        class FooVisitor(inspect.InspectVisitor):
            def visit_route(self, route):
                return 'foo'

        assert FooVisitor().process(inspect.RouteInfo('f', 'o', 'o', [])) == 'foo'


class TestStringVisitor:
    def test_class(self):
        assert issubclass(inspect.StringVisitor, inspect.InspectVisitor)

    def test_route_method(self):
        sv = inspect.StringVisitor(False)
        rm = inspect.inspect_routes(make_app())[0].methods[0]

        assert sv.process(rm) == rm.method + ' - ' + rm.function_name

    def test_route_method_verbose(self):
        sv = inspect.StringVisitor(True)
        rm = inspect.inspect_routes(make_app())[0].methods[0]

        assert sv.process(rm) == rm.method + ' - ' + rm.function_name + ' (%s)' % rm.source_info
