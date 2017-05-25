import datetime
import importlib
import logging
import re
import sqlalchemy
import sys
import warnings

class SQL(object):
    """Wrap SQLAlchemy to provide a simple SQL API."""

    def __init__(self, url, **kwargs):
        """
        Create instance of sqlalchemy.engine.Engine.

        URL should be a string that indicates database dialect and connection arguments.

        http://docs.sqlalchemy.org/en/latest/core/engines.html#sqlalchemy.create_engine
        http://docs.sqlalchemy.org/en/latest/dialects/index.html
        """
        logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)
        try:
            self.engine = sqlalchemy.create_engine(url, **kwargs)
        except Exception as e:
            e.__cause__ = None # else Python 3 prints warnings' tracebacks
            raise e

    def execute(self, text, **params):
        """
        Execute a SQL statement.
        """

        class UserDefinedType(sqlalchemy.TypeDecorator):
            """
            Add support for expandable values, a la https://bitbucket.org/zzzeek/sqlalchemy/issues/3953/expanding-parameter.
            """
            impl = sqlalchemy.types.UserDefinedType
            def process_literal_param(self, value, dialect):
                """Receive a literal parameter value to be rendered inline within a statement."""
                def process(value):
                    """Render a literal value, escaping as needed."""

                    # bool
                    if isinstance(value, bool):
                        return sqlalchemy.types.Boolean().literal_processor(dialect)(value)

                    # datetime.date
                    elif isinstance(value, datetime.date):
                        return sqlalchemy.types.String().literal_processor(dialect)(value.strftime("%Y-%m-%d"))

                    # datetime.datetime
                    elif isinstance(value, datetime.datetime):
                        return sqlalchemy.types.String().literal_processor(dialect)(value.strftime("%Y-%m-%d %H:%M:%S"))

                    # datetime.time
                    elif isinstance(value, datetime.time):
                        return sqlalchemy.types.String().literal_processor(dialect)(value.strftime("%H:%M:%S"))

                    # float
                    elif isinstance(value, float):
                        return sqlalchemy.types.Float().literal_processor(dialect)(value)

                    # int
                    elif isinstance(value, int):
                        return sqlalchemy.types.Integer().literal_processor(dialect)(value)

                    # long
                    elif sys.version_info.major != 3 and isinstance(value, long):
                        return sqlalchemy.types.Integer().literal_processor(dialect)(value)

                    # str
                    elif isinstance(value, str):
                        return sqlalchemy.types.String().literal_processor(dialect)(value)

                    # None
                    elif isinstance(value, sqlalchemy.sql.elements.Null):
                        return sqlalchemy.types.NullType().literal_processor(dialect)(value)

                    # unsupported value
                    raise RuntimeError("unsupported value")

                # process value(s), separating with commas as needed
                if type(value) is list:
                    return ", ".join([process(v) for v in value])
                else:
                    return process(value)

        # raise exceptions for warnings
        warnings.filterwarnings("error")

        # prepare, execute statement
        try:

            # construct a new TextClause clause
            statement = sqlalchemy.text(text)

            # iterate over parameters
            for key, value in params.items():

                # translate None to NULL
                if value is None:
                    value = sqlalchemy.sql.null()

                # bind parameters before statement reaches database, so that bound parameters appear in exceptions
                # http://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.expression.text
                statement = statement.bindparams(sqlalchemy.bindparam(key, value=value, type_=UserDefinedType()))

            # stringify bound parameters
            # http://docs.sqlalchemy.org/en/latest/faq/sqlexpressions.html#how-do-i-render-sql-expressions-as-strings-possibly-with-bound-parameters-inlined
            statement = str(statement.compile(compile_kwargs={"literal_binds": True}))

            # execute statement
            result = self.engine.execute(statement)

            # log statement
            self.logger.debug(statement)

            # if SELECT (or INSERT with RETURNING), return result set as list of dict objects
            if re.search(r"^\s*SELECT\s+", statement, re.I):
                rows = result.fetchall()
                return [dict(row) for row in rows]

            # if INSERT, return primary key value for a newly inserted row
            elif re.search(r"^\s*INSERT\s+", statement, re.I):
                if self.engine.url.get_backend_name() == "postgresql":
                    result = self.engine.execute(sqlalchemy.text("SELECT LASTVAL()"))
                    return result.first()[0]
                else:
                    return result.lastrowid

            # if DELETE or UPDATE, return number of rows matched
            elif re.search(r"^\s*(?:DELETE|UPDATE)\s+", statement, re.I):
                return result.rowcount

            # if some other statement, return True unless exception
            return True

        # if constraint violated, return None
        except sqlalchemy.exc.IntegrityError:
            return None

        # else raise exception
        except Exception as e:
            e.__cause__ = None # else Python 3 prints warnings' tracebacks
            raise e
